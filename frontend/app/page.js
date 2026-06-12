"use client";

import { useEffect, useRef, useState } from "react";

export default function Home() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [isComposerExpanded, setIsComposerExpanded] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const textareaRef = useRef(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    loadConversations();
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const nextHeight = Math.min(textarea.scrollHeight, 192);
    textarea.style.height = `${nextHeight}px`;
    setIsComposerExpanded(nextHeight > 44);
  }, [input]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isSending]);

  async function loadConversations() {
    try {
      const res = await fetch("/api/conversations");
      if (res.ok) {
        setConversations(await res.json());
      }
    } catch {
      // DB not configured — sidebar stays empty
    }
  }

  async function loadConversation(id) {
    try {
      const res = await fetch(`/api/conversations/${id}`);
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages);
        setCurrentConversationId(id);
        setIsSidebarOpen(false);
      }
    } catch {
      // ignore
    }
  }

  async function deleteConversation(id, e) {
    e.stopPropagation();
    try {
      await fetch(`/api/conversations/${id}`, { method: "DELETE" });
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (currentConversationId === id) {
        setMessages([]);
        setCurrentConversationId(null);
      }
    } catch {
      // ignore
    }
  }

  function newChat() {
    setMessages([]);
    setCurrentConversationId(null);
    setIsSidebarOpen(false);
  }

  async function sendMessage(event) {
    event.preventDefault();
    const content = input.trim();
    if (!content || isSending) return;

    const nextMessages = [...messages, { role: "user", content }];
    setMessages(nextMessages);
    setInput("");
    setIsSending(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: nextMessages,
          conversation_id: currentConversationId,
        }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || `Request failed with ${response.status}`);
      }

      setMessages([...nextMessages, { role: "assistant", content: data.message }]);

      if (data.conversation_id != null) {
        setCurrentConversationId(data.conversation_id);
        await loadConversations();
      }
    } catch (error) {
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: error?.message || "Unable to reach /api/chat.",
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  function formatDate(iso) {
    const d = new Date(iso);
    const diffDays = Math.floor((Date.now() - d) / 86400000);
    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString();
  }

  return (
    <div className="app-layout">
      {isSidebarOpen && (
        <div className="sidebar-overlay" onClick={() => setIsSidebarOpen(false)} />
      )}

      <aside className={`sidebar ${isSidebarOpen ? "open" : ""}`}>
        <button className="new-chat-btn" onClick={newChat}>
          + New Chat
        </button>
        <div className="conversation-list">
          {conversations.length === 0 ? (
            <p className="no-conversations">No saved conversations</p>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                className={`conversation-item ${currentConversationId === conv.id ? "active" : ""}`}
                onClick={() => loadConversation(conv.id)}
              >
                <span className="conversation-title">{conv.title}</span>
                <span className="conversation-date">{formatDate(conv.updated_at)}</span>
                <button
                  className="delete-btn"
                  onClick={(e) => deleteConversation(conv.id, e)}
                  title="Delete"
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
      </aside>

      <main className="chat-page">
        <button
          className="menu-btn"
          onClick={() => setIsSidebarOpen(!isSidebarOpen)}
          aria-label="Toggle sidebar"
        >
          ☰
        </button>

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
    </div>
  );
}
