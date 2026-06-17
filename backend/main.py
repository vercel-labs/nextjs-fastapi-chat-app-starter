from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from typing import Literal
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from vercel.oidc.aio import get_vercel_oidc_token

from storage import close_store, get_store


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Note: get_store cannot be used here because it depends on a Vercel OIDC token 
    # for the AuroraStore to work, which is only available inside a request context.
    try:
        yield
    finally:
        await close_store()


app = FastAPI(
    title="Chat API",
    description="FastAPI backend for the chat app.",
    version="0.1.0",
    lifespan=lifespan,
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    messages: list[Message]


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class Conversation(ConversationSummary):
    messages: list[Message]


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    conversation: ConversationSummary


class CreateConversationRequest(BaseModel):
    title: str = "New chat"


def get_model_name() -> str:
    return "gateway:anthropic/claude-haiku-4.5"


def get_gateway_params() -> dict:
    return {"providerOptions": {"gateway": {"order": ["bedrock"]}}}


async def ensure_ai_gateway_auth() -> bool:
    if os.environ.get("AI_GATEWAY_API_KEY"):
        return True

    token = await get_vercel_oidc_token()

    if not token:
        return False

    os.environ["AI_GATEWAY_API_KEY"] = token
    return True


async def generate_reply(messages: list[Message]) -> str:
    last_user_message = next(
        (message.content.strip() for message in reversed(messages) if message.role == "user"),
        "",
    )

    return f"not implemented: you said {last_user_message}"


@app.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations() -> list[ConversationSummary]:
    # TODO: Implement this
    raise HTTPException(status_code=501, detail="Not implemented")


@app.post("/conversations", response_model=ConversationSummary)
async def create_conversation(
    request: CreateConversationRequest,
) -> ConversationSummary:
    # TODO: Implement this
    raise HTTPException(status_code=501, detail="Not implemented")


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    # TODO: Implement this
    raise HTTPException(status_code=501, detail="Not implemented")


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    # TODO: Implement this
    raise HTTPException(status_code=501, detail="Not implemented")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    conversation_id = request.conversation_id or uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()

    return ChatResponse(
        conversation_id=conversation_id,
        message=await generate_reply(request.messages),
        conversation=ConversationSummary(
            id=conversation_id,
            title="New chat",
            created_at=now,
            updated_at=now,
        ),
    )
