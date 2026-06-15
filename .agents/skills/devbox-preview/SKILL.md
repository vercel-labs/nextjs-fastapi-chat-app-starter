---
name: devbox-preview
description: Project knowledge for making this repo preview correctly from Vercel Devbox/Sandbox. Use when configuring Next.js dev settings, explaining how users preview the app from Devbox, or responding to localhost, Sandbox URL, port 3000, or cross-origin dev-resource issues.
---

# Devbox Preview

This starter is used in a workshop where some users run the app inside Vercel Devbox instead of on their laptop. Preserve this setup so preview works without users debugging Devbox internals.

## Required app configuration

The frontend must allow Vercel Sandbox preview origins during Next.js development. Keep this in `frontend/next.config.js`:

```js
allowedDevOrigins: ["*.vercel.run"]
```

Without this, Next.js can serve the page but block dev-only resources such as HMR from `https://sb-...vercel.run`, causing confusing preview failures.

## Preview model

- In Devbox, `localhost` means the remote box, not the user's laptop.
- Users should open the published Sandbox URL for port 3000, usually `https://sb-...vercel.run`.
- Do not tell Devbox users to open their laptop's `http://localhost:3000`.
- The frontend and backend are both reached through Vercel dev on port 3000:
  - frontend: `/`
  - backend: `/api/*`

## User-facing guidance

When explaining how to preview from Devbox, tell the user:

1. In the Devbox SSH session, run Vercel dev bound to port 3000:

```bash
vercel dev -L --listen 0.0.0.0:3000
```

2. From a local terminal outside the Devbox SSH session, publish port 3000:

```bash
SANDBOX_ID=$(devbox get --output json | python3 -c 'import json, sys; print(json.load(sys.stdin)["response"]["devboxes"][0]["sandboxId"])')
sandbox config ports "$SANDBOX_ID" -p 3000
```

3. Open the `https://sb-...vercel.run` URL printed by the `sandbox config ports` command.

## Troubleshooting context

- If `curl -i http://127.0.0.1:3000/` works inside Devbox but the browser fails, suspect Sandbox port publishing or `allowedDevOrigins`.
- If the browser shows a cross-origin dev-resource warning, check `frontend/next.config.js` and restart `vercel dev`.
- If curl inside Devbox returns 500, inspect the app error in the `vercel dev` terminal logs.
