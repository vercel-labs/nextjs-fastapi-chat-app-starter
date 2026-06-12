"use client";

import { useEffect, useRef, useState } from "react";

export default function Home() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [isComposerExpanded, setIsComposerExpanded] = useState(false);
  const textareaRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    const textarea = textareaRef.current;

    if (!textarea) {
      return;
    }

    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, 192);
    textarea.style.height = `${nextHeight}px`;
    setIsComposerExpanded(nextHeight > 44);
  }, [input]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  async function sendMessage(event) {
    event.preventDefault();
    const content = input.trim();

    if (!content || isSending) {
      return;
    }

    const nextMessages = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setInput("");
    setIsSending(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ messages: nextMessages }),
      });

      const data = await response.json();
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: data.message,
        },
      ]);
    } catch {
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: "Unable to reach /api/chat.",
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <main className="chat-page">
      <div className="messages">
        {messages.length === 0 ? (
          <h1>How can I help?</h1>
        ) : (
          messages.map((message, index) => (
            <div className={`message ${message.role}`} key={index}>
              {message.content}
            </div>
          ))
        )}

        {isSending && (
          <div className="message assistant pending">
            <span />
            <span />
            <span />
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form onSubmit={sendMessage} className="composer">
        <div className={`composer-inner ${isComposerExpanded ? "expanded" : ""}`}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Message"
            rows={1}
          />
          <button type="submit" disabled={!input.trim() || isSending}>
            Send
          </button>
        </div>
      </form>
    </main>
  );
}
