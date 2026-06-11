# Chat App Template

- `frontend/`: Next.js app mounted at `/`
- `backend/`: FastAPI app mounted at `/api`

## Project Structure

```txt
.
├── backend/
│   ├── main.py
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
