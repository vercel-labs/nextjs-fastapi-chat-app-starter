from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="Chat API",
    description="FastAPI backend for the chat app.",
    version="0.1.0",
)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class ChatResponse(BaseModel):
    message: str


def generate_reply(messages: list[Message]) -> str:
    """Produce an assistant reply for the conversation.

    This is a self-contained echo-style responder so the app works end to end
    without external credentials. Swap the body for a call to your LLM provider
    (e.g. the AI Gateway) to make it a real assistant.
    """
    last_user = next(
        (m.content for m in reversed(messages) if m.role == "user"),
        "",
    )

    if not last_user.strip():
        return "Hi! Send me a message and I'll reply."

    return f'You said: "{last_user.strip()}"\n\nThis is a stub reply from the FastAPI backend.'


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return ChatResponse(message=generate_reply(request.messages))
