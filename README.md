# Chat App Template

- `frontend/`: Next.js app mounted at `/`
- `backend/`: FastAPI app mounted at `/api`

## Project Structure

```txt
.
├── backend/
│   ├── main.py
│   ├── storage.py
│   └── pyproject.toml
├── frontend/
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.js
│   │   └── page.js
│   └── package.json
└── vercel.json
```

## Local Development

Run the services together:

```bash
cd ..
vercel dev -L
```

Local development stores chat history in SQLite at
`backend/.data/chat-history.sqlite3` by default. Override the path with
`SQLITE_PATH` if needed.

## Production Storage

In Vercel preview and production (`VERCEL_ENV=preview` or `production`), chat
history uses Aurora PostgreSQL with IAM authentication via Vercel OIDC.
Configure these environment variables:

- `PGHOST`: Aurora cluster endpoint
- `PGUSER`: database user, defaults to `postgres`
- `PGDATABASE`: database name, defaults to `postgres`
- `AWS_REGION`: AWS region for STS and RDS
- `AWS_ROLE_ARN`: role assumed with Vercel's OIDC token

Set `STORE=aurora` to force Aurora outside production, or
`STORE=sqlite` to force SQLite. For an ephemeral demo store, set
`STORE=runtime_cache` to use Vercel Runtime Cache instead. Runtime
Cache is regional and evictable, so it is useful for demos but should not be
treated as durable chat history.

## AI Model

The backend uses the Python `ai` SDK with Vercel AI Gateway. It first uses
`AI_GATEWAY_API_KEY` when present, then falls back to a Vercel OIDC token via the
Vercel Python SDK. Set `AI_SDK_DEFAULT_MODEL` to override the default Gateway
model. Without Gateway auth, the app keeps using the local stub reply so
`vercel dev` works end to end.
