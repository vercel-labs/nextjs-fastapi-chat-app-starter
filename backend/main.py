from fastapi import FastAPI, status
from fastapi.responses import JSONResponse


app = FastAPI(
    title="Chat API Template",
    description="Stub FastAPI backend for a chat app template.",
    version="0.1.0",
)


@app.post("/chat")
async def chat():
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "message": "TODO: implement the /api/chat endpoint.",
        },
    )
