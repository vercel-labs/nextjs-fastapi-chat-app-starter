from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite
import asyncpg
import boto3
from vercel.oidc import decode_oidc_payload
from vercel.oidc.aio import get_vercel_oidc_token


MessageRecord = dict[str, str]
ConversationSummary = dict[str, str]
ConversationRecord = dict[str, Any]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _serialize_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    return str(value)


def _store_kind() -> str:
    store = os.environ.get("STORE", "").lower()

    if store in {"aurora", "runtime_cache", "sqlite"}:
        return store

    if os.environ.get("VERCEL_ENV") in {"production", "preview"}:
        return "aurora"

    return "sqlite"


class SQLiteStore:
    def __init__(self) -> None:
        default_path = Path(__file__).resolve().parent / ".data" / "chat-history.sqlite3"
        self.path = Path(os.environ.get("SQLITE_PATH", default_path))
        self.connection: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row

        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                position INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.connection.commit()

    def _db(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("SQLite store has not been initialized")

        return self.connection

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    async def list_conversations(self) -> list[ConversationSummary]:
        cursor = await self._db().execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            ORDER BY updated_at DESC
            """
        )
        rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def create_conversation(self, title: str) -> ConversationSummary:
        conversation_id = _new_id()
        now = _now()
        await self._db().execute(
            """
            INSERT INTO conversations (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, now, now),
        )
        await self._db().commit()

        return {
            "id": conversation_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        cursor = await self._db().execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        )
        conversation = await cursor.fetchone()

        if conversation is None:
            return None

        cursor = await self._db().execute(
            """
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY position ASC
            """,
            (conversation_id,),
        )
        messages = await cursor.fetchall()
        record = dict(conversation)
        record["messages"] = [dict(message) for message in messages]

        return record

    async def replace_messages(
        self,
        conversation_id: str,
        messages: list[MessageRecord],
        title: str | None = None,
    ) -> ConversationSummary:
        now = _now()
        db = self._db()
        await db.execute("BEGIN")

        try:
            if title is not None:
                await db.execute(
                    """
                    UPDATE conversations
                    SET title = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (title, now, conversation_id),
                )
            else:
                await db.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )

            await db.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )

            for position, message in enumerate(messages):
                await db.execute(
                    """
                    INSERT INTO messages (
                        id, conversation_id, role, content, position, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(),
                        conversation_id,
                        message["role"],
                        message["content"],
                        position,
                        now,
                    ),
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        cursor = await db.execute(
            """
            SELECT id, title, created_at, updated_at
            FROM conversations
            WHERE id = ?
            """,
            (conversation_id,),
        )
        row = await cursor.fetchone()

        if row is None:
            raise RuntimeError("Conversation was not found after saving messages")

        return dict(row)

    async def delete_conversation(self, conversation_id: str) -> bool:
        db = self._db()
        await db.execute("BEGIN")

        try:
            await db.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            cursor = await db.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return cursor.rowcount > 0


class RuntimeCacheStore:
    INDEX_KEY = "conversations:index"

    def __init__(self) -> None:
        self.cache: Any | None = None
        self.ttl = int(os.environ.get("CHAT_HISTORY_CACHE_TTL", "604800"))
        self.namespace = os.environ.get("CHAT_HISTORY_CACHE_NAMESPACE", "chat-history")

    async def init(self) -> None:
        from vercel.cache import AsyncRuntimeCache

        self.cache = AsyncRuntimeCache(namespace=self.namespace)

    def _cache(self) -> Any:
        if self.cache is None:
            raise RuntimeError("Runtime Cache store has not been initialized")

        return self.cache

    def _options(self, *tags: str) -> dict[str, Any]:
        return {
            "ttl": self.ttl,
            "tags": ["chat-history", *tags],
            "name": "chat-history",
        }

    def _conversation_key(self, conversation_id: str) -> str:
        return f"conversation:{conversation_id}"

    async def close(self) -> None:
        self.cache = None

    async def _get_index(self) -> list[ConversationSummary]:
        index = await self._cache().get(self.INDEX_KEY)

        if not isinstance(index, list):
            return []

        return [
            {
                "id": item["id"],
                "title": item["title"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in index
            if isinstance(item, dict)
            and all(
                key in item
                for key in ("id", "title", "created_at", "updated_at")
            )
        ]

    async def _set_index(self, index: list[ConversationSummary]) -> None:
        await self._cache().set(
            self.INDEX_KEY,
            sorted(index, key=lambda item: item["updated_at"], reverse=True),
            self._options("conversations"),
        )

    async def list_conversations(self) -> list[ConversationSummary]:
        return await self._get_index()

    async def create_conversation(self, title: str) -> ConversationSummary:
        conversation_id = _new_id()
        now = _now()
        conversation = {
            "id": conversation_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }
        record: ConversationRecord = {**conversation, "messages": []}

        await self._cache().set(
            self._conversation_key(conversation_id),
            record,
            self._options("conversations", f"conversation:{conversation_id}"),
        )

        index = await self._get_index()
        await self._set_index([conversation, *index])

        return conversation

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        record = await self._cache().get(self._conversation_key(conversation_id))

        if not isinstance(record, dict):
            return None

        if not all(
            key in record
            for key in ("id", "title", "created_at", "updated_at", "messages")
        ):
            return None

        return {
            "id": record["id"],
            "title": record["title"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "messages": record["messages"],
        }

    async def replace_messages(
        self,
        conversation_id: str,
        messages: list[MessageRecord],
        title: str | None = None,
    ) -> ConversationSummary:
        existing = await self.get_conversation(conversation_id)

        if existing is None:
            raise RuntimeError("Conversation not found")

        now = _now()
        conversation = {
            "id": conversation_id,
            "title": title or existing["title"],
            "created_at": existing["created_at"],
            "updated_at": now,
        }
        record: ConversationRecord = {**conversation, "messages": messages}

        await self._cache().set(
            self._conversation_key(conversation_id),
            record,
            self._options("conversations", f"conversation:{conversation_id}"),
        )

        index = await self._get_index()
        next_index = [
            item for item in index if item["id"] != conversation_id
        ]
        await self._set_index([conversation, *next_index])

        return conversation

    async def delete_conversation(self, conversation_id: str) -> bool:
        index = await self._get_index()
        next_index = [item for item in index if item["id"] != conversation_id]
        found = len(next_index) != len(index)

        await self._cache().delete(self._conversation_key(conversation_id))

        if found:
            await self._set_index(next_index)

        return found


class AuroraStore:
    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        self.pool = await asyncpg.create_pool(
            host=os.environ["PGHOST"],
            port=5432,
            user=os.environ.get("PGUSER", "postgres"),
            password=await self._generate_auth_token(),
            database=os.environ.get("PGDATABASE", "postgres"),
            ssl="require",
            min_size=0,
            max_size=int(os.environ.get("PGPOOL_MAX_SIZE", "4")),
        )

        async with self._pool().acquire() as connection:
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id VARCHAR(64) PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id VARCHAR(64) PRIMARY KEY,
                    conversation_id VARCHAR(64) NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    content TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )

    def _pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("Aurora store has not been initialized")

        return self.pool

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _get_aws_credentials(self) -> dict[str, Any]:
        token = await get_vercel_oidc_token()
        payload = decode_oidc_payload(token)
        project_id = payload.get("project_id")

        def assume_role() -> dict[str, Any]:
            sts = boto3.client("sts", region_name=os.environ["AWS_REGION"])
            response = sts.assume_role_with_web_identity(
                RoleArn=os.environ["AWS_ROLE_ARN"],
                RoleSessionName=f"aurora-fastapi-{project_id or 'session'}",
                WebIdentityToken=token,
            )
            return response["Credentials"]

        return await asyncio.to_thread(assume_role)

    async def _generate_auth_token(self) -> str:
        credentials = await self._get_aws_credentials()

        def generate_token() -> str:
            client = boto3.client(
                "rds",
                region_name=os.environ["AWS_REGION"],
                aws_access_key_id=credentials["AccessKeyId"],
                aws_secret_access_key=credentials["SecretAccessKey"],
                aws_session_token=credentials["SessionToken"],
            )
            return client.generate_db_auth_token(
                DBHostname=os.environ["PGHOST"],
                Port=5432,
                DBUsername=os.environ.get("PGUSER", "postgres"),
            )

        return await asyncio.to_thread(generate_token)

    async def list_conversations(self) -> list[ConversationSummary]:
        async with self._pool().acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC
                """
            )

        return [self._summary(row) for row in rows]

    async def create_conversation(self, title: str) -> ConversationSummary:
        conversation_id = _new_id()
        now = datetime.now(timezone.utc)

        async with self._pool().acquire() as connection:
            row = await connection.fetchrow(
                """
                INSERT INTO conversations (id, title, created_at, updated_at)
                VALUES ($1, $2, $3, $4)
                RETURNING id, title, created_at, updated_at
                """,
                conversation_id,
                title,
                now,
                now,
            )

        if row is None:
            raise RuntimeError("Aurora did not return the created conversation")

        return self._summary(row)

    async def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        async with self._pool().acquire() as connection:
            conversation = await connection.fetchrow(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = $1
                """,
                conversation_id,
            )

            if conversation is None:
                return None

            messages = await connection.fetch(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id = $1
                ORDER BY position ASC
                """,
                conversation_id,
            )

        record: ConversationRecord = dict(self._summary(conversation))
        record["messages"] = [
            {"role": message["role"], "content": message["content"]}
            for message in messages
        ]

        return record

    async def replace_messages(
        self,
        conversation_id: str,
        messages: list[MessageRecord],
        title: str | None = None,
    ) -> ConversationSummary:
        now = datetime.now(timezone.utc)

        async with self._pool().acquire() as connection:
            async with connection.transaction():
                if title is not None:
                    await connection.execute(
                        """
                        UPDATE conversations
                        SET title = $1, updated_at = $2
                        WHERE id = $3
                        """,
                        title,
                        now,
                        conversation_id,
                    )
                else:
                    await connection.execute(
                        "UPDATE conversations SET updated_at = $1 WHERE id = $2",
                        now,
                        conversation_id,
                    )

                await connection.execute(
                    "DELETE FROM messages WHERE conversation_id = $1",
                    conversation_id,
                )

                for position, message in enumerate(messages):
                    await connection.execute(
                        """
                        INSERT INTO messages (
                            id, conversation_id, role, content, position, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        _new_id(),
                        conversation_id,
                        message["role"],
                        message["content"],
                        position,
                        now,
                    )

            row = await connection.fetchrow(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = $1
                """,
                conversation_id,
            )

        if row is None:
            raise RuntimeError("Conversation was not found after saving messages")

        return self._summary(row)

    async def delete_conversation(self, conversation_id: str) -> bool:
        async with self._pool().acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "DELETE FROM messages WHERE conversation_id = $1",
                    conversation_id,
                )
                result = await connection.execute(
                    "DELETE FROM conversations WHERE id = $1",
                    conversation_id,
                )

        return result.endswith(" 1")

    def _summary(self, row: asyncpg.Record) -> ConversationSummary:
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": _serialize_timestamp(row["created_at"]),
            "updated_at": _serialize_timestamp(row["updated_at"]),
        }


Store = SQLiteStore | RuntimeCacheStore | AuroraStore
_store: Store | None = None


async def get_store() -> Store:
    global _store

    if _store is None:
        store_kind = _store_kind()

        if store_kind == "aurora":
            _store = AuroraStore()
        elif store_kind == "runtime_cache":
            _store = RuntimeCacheStore()
        else:
            _store = SQLiteStore()

        await _store.init()

    return _store


async def close_store() -> None:
    global _store

    if _store is not None:
        await _store.close()
        _store = None
