import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import ai
import asyncpg
import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


# Environment

logger = logging.getLogger("chat_api")


def _load_local_env() -> None:
    """FastAPI does not load Next/Vercel .env files unless we do it explicitly."""
    backend_dir = Path(__file__).resolve().parent
    for env_file in (backend_dir.parent / ".env.local", backend_dir / ".env.local"):
        load_dotenv(env_file, override=False)


_load_local_env()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class ServiceConfigurationError(RuntimeError):
    pass


# Models

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    message: str
    conversation_id: int | None = None


class ConversationSummary(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(BaseModel):
    id: int
    title: str
    messages: list[Message]


class ServiceHealth(BaseModel):
    configured: bool
    mode: str | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    ai: ServiceHealth
    database: ServiceHealth


# AI client

_ai_model: ai.Model | None = None

_AI_GATEWAY_MODEL_ID = _env("AI_GATEWAY_MODEL", "anthropic/claude-haiku-4.5")

_AI_MAX_TOKENS = 4096

_SYSTEM_PROMPT = "You are a helpful, friendly assistant."


def _ai_gateway_key() -> str:
    return _env("AI_GATEWAY_API_KEY")


def _ai_unavailable_detail() -> str:
    return (
        "AI is not configured. Set AI_GATEWAY_API_KEY in .env.local or in the "
        "Vercel environment variables."
    )


def _ai_health() -> ServiceHealth:
    if not _ai_gateway_key():
        return ServiceHealth(configured=False, detail=_ai_unavailable_detail())
    return ServiceHealth(configured=True, mode="gateway")


def _get_ai_model() -> ai.Model:
    global _ai_model
    api_key = _ai_gateway_key()
    if not api_key:
        raise ServiceConfigurationError(_ai_unavailable_detail())

    if _ai_model is None:
        # Pass the stripped key explicitly so accidental trailing newlines are
        # not sent in the Authorization header.
        _ai_model = ai.Model(
            _AI_GATEWAY_MODEL_ID,
            provider=ai.get_provider("gateway", api_key=api_key),
        )
    return _ai_model


async def _generate_reply(messages: list[Message]) -> str:
    conversation = [ai.system_message(_SYSTEM_PROMPT)]
    for m in messages:
        if m.role == "user":
            conversation.append(ai.user_message(m.content))
        elif m.role == "assistant":
            conversation.append(ai.assistant_message(m.content))

    async with ai.stream(
        _get_ai_model(), conversation, params={"max_tokens": _AI_MAX_TOKENS}
    ) as stream:
        async for _event in stream:
            pass
        reply = stream.text

    return reply or "I couldn't generate a response."


# Database

DbAuthMode = Literal["password", "iam"]

pool: asyncpg.Pool | None = None
_DB_IAM_ENV_VARS = ("AWS_REGION", "AWS_ROLE_ARN", "VERCEL_OIDC_TOKEN")
_db_startup_error: str | None = None


def _db_auth_mode() -> DbAuthMode | None:
    if not _env("PGHOST"):
        return None
    if _env("PGPASSWORD"):
        return "password"
    if all(_env(name) for name in _DB_IAM_ENV_VARS):
        return "iam"
    return None


def _db_unavailable_detail() -> str:
    if not _env("PGHOST"):
        return (
            "Database is not configured. Set PGHOST plus either PGPASSWORD or "
            "AWS_REGION, AWS_ROLE_ARN, and VERCEL_OIDC_TOKEN."
        )

    missing = [name for name in _DB_IAM_ENV_VARS if not _env(name)]
    return (
        "Database auth is incomplete. Set PGPASSWORD for password auth or set "
        "all IAM auth variables. Missing IAM variables: " + ", ".join(missing)
    )


def _db_health() -> ServiceHealth:
    mode = _db_auth_mode()
    if mode is None:
        return ServiceHealth(configured=False, detail=_db_unavailable_detail())
    if _db_startup_error:
        return ServiceHealth(configured=True, mode=mode, detail=_db_startup_error)
    return ServiceHealth(configured=True, mode=mode)


def _get_aws_credentials() -> dict:
    if _db_auth_mode() != "iam":
        raise ServiceConfigurationError(_db_unavailable_detail())

    sts = boto3.client("sts", region_name=_env("AWS_REGION"))
    resp = sts.assume_role_with_web_identity(
        RoleArn=_env("AWS_ROLE_ARN"),
        RoleSessionName="aurora-chat-session",
        WebIdentityToken=_env("VERCEL_OIDC_TOKEN"),
    )
    return resp["Credentials"]


def _generate_auth_token() -> str:
    creds = _get_aws_credentials()
    rds = boto3.client(
        "rds",
        region_name=_env("AWS_REGION"),
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    return rds.generate_db_auth_token(
        DBHostname=_env("PGHOST"),
        Port=int(_env("PGPORT", "5432")),
        DBUsername=_env("PGUSER", "postgres"),
    )


def _db_connection_kwargs(mode: DbAuthMode) -> dict[str, object]:
    return {
        "host": _env("PGHOST"),
        "port": int(_env("PGPORT", "5432")),
        "user": _env("PGUSER", "postgres"),
        "password": (
            _env("PGPASSWORD") if mode == "password" else _generate_auth_token()
        ),
        "database": _env("PGDATABASE", "postgres"),
        "ssl": "require",
    }


async def get_pool() -> asyncpg.Pool:
    global pool
    mode = _db_auth_mode()
    if mode is None:
        raise ServiceConfigurationError(_db_unavailable_detail())

    if pool is None:
        pool = await asyncpg.create_pool(**_db_connection_kwargs(mode))
    return pool


async def require_pool() -> asyncpg.Pool:
    if _db_startup_error:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {_db_startup_error}",
        )
    try:
        return await get_pool()
    except ServiceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id          BIGSERIAL PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT 'New Conversation',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,
    content          TEXT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _db_startup_error
    mode = _db_auth_mode()
    if mode is None:
        logger.info(_db_unavailable_detail())
    else:
        try:
            db = await get_pool()
            await db.execute(_SCHEMA)
        except Exception as exc:
            _db_startup_error = str(exc)
            logger.exception("Database initialization failed")

    try:
        yield
    finally:
        if pool is not None:
            await pool.close()


# App

app = FastAPI(
    title="Chat API",
    description="FastAPI backend for the chat app.",
    version="0.1.0",
    lifespan=lifespan,
)


# Health

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(ai=_ai_health(), database=_db_health())


# Chat

def _chat_title(messages: list[Message]) -> str:
    first_user = next(
        (m.content for m in messages if m.role == "user"),
        "New Conversation",
    )
    return first_user[:60].strip() or "New Conversation"


def _last_user_message(messages: list[Message]) -> Message | None:
    return next((m for m in reversed(messages) if m.role == "user"), None)


async def _insert_message(
    conn: asyncpg.Connection,
    conversation_id: int,
    role: str,
    content: str,
) -> None:
    await conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES ($1, $2, $3)",
        conversation_id,
        role,
        content,
    )


async def _persist_chat(request: ChatRequest, reply: str) -> int:
    db = await get_pool()
    conv_id = request.conversation_id
    last_user_msg = _last_user_message(request.messages)

    async with db.acquire() as conn:
        async with conn.transaction():
            if conv_id is None:
                row = await conn.fetchrow(
                    "INSERT INTO conversations (title) VALUES ($1) RETURNING id",
                    _chat_title(request.messages),
                )
                conv_id = row["id"]

            assert conv_id is not None
            if last_user_msg:
                await _insert_message(conn, conv_id, "user", last_user_msg.content)

            await _insert_message(conn, conv_id, "assistant", reply)
            await conn.execute(
                "UPDATE conversations SET updated_at = NOW() WHERE id = $1",
                conv_id,
            )

    return conv_id


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        reply = await _generate_reply(request.messages)
    except ServiceConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if _db_auth_mode() is None or _db_startup_error:
        return ChatResponse(message=reply)

    try:
        conv_id = await _persist_chat(request, reply)
        return ChatResponse(message=reply, conversation_id=conv_id)
    except Exception:
        logger.exception("Chat response generated but persistence failed")
        return ChatResponse(message=reply)


# Conversations

@app.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations() -> list[ConversationSummary]:
    db = await require_pool()
    rows = await db.fetch(
        "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
    )
    return [ConversationSummary(**dict(row)) for row in rows]


@app.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: int) -> ConversationDetail:
    db = await require_pool()
    conv = await db.fetchrow(
        "SELECT id, title FROM conversations WHERE id = $1",
        conversation_id,
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    rows = await db.fetch(
        "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY created_at",
        conversation_id,
    )
    return ConversationDetail(
        id=conv["id"],
        title=conv["title"],
        messages=[Message(**dict(row)) for row in rows],
    )


@app.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int) -> None:
    db = await require_pool()
    await db.execute("DELETE FROM conversations WHERE id = $1", conversation_id)
