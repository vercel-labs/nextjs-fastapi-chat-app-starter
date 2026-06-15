---
name: python-aurora
description: AWS Aurora PostgreSQL and Aurora DSQL Python integration using asyncpg. Use when building Python backends with Aurora PostgreSQL or Aurora DSQL.
---

# AWS Aurora Python Integration

Use `asyncpg` for queries, `boto3` for IAM auth token generation, and the Vercel Python SDK for OIDC token retrieval. On Vercel, AWS credentials are obtained via OIDC federation: call `get_vercel_oidc_token()` from `vercel.oidc.aio`, then exchange that token for temporary AWS credentials via `sts.assume_role_with_web_identity()`. Do not rely on `VERCEL_OIDC_TOKEN` as an environment variable; it is not available in production runtime.

## Guidelines

- Use `asyncpg.create_pool()` with the IAM token as the password. Async access avoids blocking FastAPI's event loop.
- Authenticate via OIDC: call `get_vercel_oidc_token()` to get the Vercel OIDC token, pass it to `sts.assume_role_with_web_identity()` to get temporary credentials, then use those credentials with `rds.generate_db_auth_token()`.
- Use `$1`, `$2` parameter syntax for queries (asyncpg's native format). Never use f-strings for SQL.
- Enable SSL (`ssl="require"`) — IAM auth requires an encrypted connection.
- Wrap route handlers in try/except and return clear error JSON. Unhandled errors get buried in deep ASGI stack traces and could lead you in the wrong direction.

## Aurora DSQL Restrictions

If the target is Aurora DSQL (not standard Aurora PostgreSQL), these PostgreSQL features are **not available**:

- No `SERIAL` / `BIGSERIAL` / `SMALLSERIAL` — use `VARCHAR` IDs (e.g. nanoid)
- No temporary tables, triggers, sequences, partitions
- No `ON UPDATE` clause in `CREATE TABLE`
- Must `COMMIT` after each DDL statement
- Must use `CREATE INDEX ASYNC` (no `ASC`/`DESC` in index ordering)

## Dependencies

- `asyncpg`: async PostgreSQL driver
- `boto3`: AWS SDK for OIDC credential exchange and IAM token generation
- `vercel`: Vercel Python SDK for runtime OIDC token retrieval

## Environment Variables

- `PGHOST` — Aurora cluster endpoint
- `PGUSER` — database user (default: `postgres`)
- `PGDATABASE` — database name (default: `postgres`)
- `AWS_REGION` — AWS region
- `AWS_ROLE_ARN` — IAM role to assume via OIDC

## Setup

```python
import os
import asyncpg
import boto3
from vercel.oidc import decode_oidc_payload
from vercel.oidc.aio import get_vercel_oidc_token


async def _get_aws_credentials() -> dict:
    """Exchange Vercel's OIDC token for temporary AWS credentials."""
    token = await get_vercel_oidc_token()
    payload = decode_oidc_payload(token)
    project_id = payload.get("project_id")

    sts = boto3.client("sts", region_name=os.environ["AWS_REGION"])
    resp = sts.assume_role_with_web_identity(
        RoleArn=os.environ["AWS_ROLE_ARN"],
        RoleSessionName=f"aurora-fastapi-{project_id or 'session'}",
        WebIdentityToken=token,
    )
    return resp["Credentials"]


async def generate_auth_token() -> str:
    creds = await _get_aws_credentials()
    client = boto3.client(
        "rds",
        region_name=os.environ["AWS_REGION"],
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
    return client.generate_db_auth_token(
        DBHostname=os.environ["PGHOST"],
        Port=5432,
        DBUsername=os.environ.get("PGUSER", "postgres"),
    )


pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            host=os.environ["PGHOST"],
            port=5432,
            user=os.environ.get("PGUSER", "postgres"),
            password=await generate_auth_token(),
            database=os.environ.get("PGDATABASE", "postgres"),
            ssl="require",
        )
    return pool
```

## Usage

```python
# Error handling omitted for brevity — see Guidelines
from fastapi import FastAPI

app = FastAPI()

@app.get("/todos")
async def list_todos():
    p = await get_pool()
    rows = await p.fetch("SELECT * FROM todos ORDER BY created_at DESC")
    return [dict(r) for r in rows]

@app.post("/todos")
async def create_todo(title: str):
    p = await get_pool()
    row = await p.fetchrow("INSERT INTO todos (title) VALUES ($1) RETURNING *", title)
    return dict(row)

@app.patch("/todos/{todo_id}")
async def update_todo(todo_id: int, completed: bool):
    p = await get_pool()
    row = await p.fetchrow("UPDATE todos SET completed = $1 WHERE id = $2 RETURNING *", completed, todo_id)
    return dict(row)

@app.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int):
    p = await get_pool()
    await p.execute("DELETE FROM todos WHERE id = $1", todo_id)
```
