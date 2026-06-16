---
name: vercel-services
description: Project knowledge for configuring Vercel Services in this Next.js and FastAPI starter. Use when editing vercel.json, adding services, debugging frontend-to-backend routing, or explaining Vercel Services local development and deployment.
---

# Vercel Services

This starter deploys a Next.js frontend and FastAPI backend as one Vercel project using Services. Keep the repo as a single deployable unit with shared environment variables, one deployment URL, and path-based routing.

## Project model

- Frontend service: `frontend/`, Next.js, mounted at `/`.
- Backend service: `backend/main.py`, FastAPI, mounted at `/api`.
- Browser calls should use relative paths such as `fetch("/api/chat")`; do not hard-code localhost or a separate backend domain.
- Backend routes are written relative to the backend app. For example, `@app.post("/chat")` is reachable at `/api/chat` because Vercel adds the service prefix.

## Required Vercel configuration

Define services in the root `vercel.json` with `experimentalServices` and `mount`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "experimentalServices": {
    "frontend": {
      "entrypoint": "frontend",
      "framework": "nextjs",
      "mount": "/"
    },
    "backend": {
      "entrypoint": "backend/main.py",
      "framework": "fastapi",
      "mount": "/api"
    }
  }
}
```

When creating or repairing Services config, use `mount` and update all service entries consistently.

## Configuration guidelines

- Keep service names stable (`frontend`, `backend`) unless the repo structure changes.
- Set `framework` when the framework should not rely on auto-detection (`nextjs`, `fastapi`, `express`, etc.).
- Use `memory`, `maxDuration`, `includeFiles`, and `excludeFiles` only for service-specific needs.
- Do not add rewrites to proxy `/api` to FastAPI; Services routing should own that path prefix.
- In Vercel project settings, the framework must be set to Services for deployments that use `experimentalServices`.

## Local development

Run all services together from the repo root:

```bash
vercel dev -L
```

Use `-L` / `--local` so local development does not require authenticating to Vercel Cloud. In Devbox/Sandbox preview flows, follow the `devbox-preview` skill for the correct bind address and published port.

## Troubleshooting

- If `/api/chat` 404s, confirm the backend service prefix is `/api` and the FastAPI route is `/chat`, not `/api/chat`.
- If the frontend cannot reach the backend locally, confirm requests are going through `vercel dev`, not a standalone Next.js dev server.
- If deployment builds only one app, check that the project framework setting is Services and `experimentalServices` exists in root `vercel.json`.
- If changing mount paths, update frontend fetch paths, docs, and any tests together.
