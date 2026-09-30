import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

type FamilyNode = { name: string; status: string };
type Chat = { id: string; title: string; updated_at: string };
type Message = {
  role: "user" | "assistant";
  text: string;
  status?: string;
  error?: string;
};

const FAMILY_REFRESH_MS = 15_000;

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

export default function App() {
  const [family, setFamily] = useState<FamilyNode[] | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [seriesId, setSeriesId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadChats = () => getJson<Chat[]>("/api/chats").then(setChats).catch(console.error);

  useEffect(() => {
    const loadFamily = () =>
      getJson<FamilyNode[]>("/api/family").then(setFamily).catch(console.error);
    loadFamily();
    loadChats();
    const timer = setInterval(loadFamily, FAMILY_REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Change only the last message: the assistant reply being streamed.
  const updateReply = (change: (m: Message) => Message) =>
    setMessages((prev) => [...prev.slice(0, -1), change(prev[prev.length - 1])]);

  const newChat = () => {
    setSeriesId(null);
    setMessages([]);
  };

  const openChat = async (id: string) => {
    setSeriesId(id);
    setMessages(await getJson<Message[]>(`/api/chats/${id}`));
  };

  const send = async () => {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", text: prompt },
      { role: "assistant", text: "", status: "Sending…" },
    ]);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt, series_id: seriesId }),
      });
      const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const frames = buffer.split("\n\n");
        buffer = frames.pop()!;
        for (const frame of frames) {
          const event = JSON.parse(frame.replace(/^data: /, ""));
          if (event.type === "series") setSeriesId(event.series_id);
          else if (event.type === "status") updateReply((m) => ({ ...m, status: event.text }));
          else if (event.type === "delta")
            updateReply((m) => ({ ...m, text: m.text + event.text, status: undefined }));
          else if (event.type === "error")
            updateReply((m) => ({ ...m, status: undefined, error: event.text }));
        }
      }
    } catch (err) {
      updateReply((m) => ({ ...m, status: undefined, error: String(err) }));
    } finally {
      updateReply((m) => ({ ...m, status: undefined }));
      setBusy(false);
      loadChats();
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">F</div>
          <div>
            <div className="brand-name">Family Hub</div>
            <div className="brand-sub">Family scheduling on Flower</div>
          </div>
        </div>

        <button className="new-chat" onClick={newChat}>
          <span>+</span> New conversation
        </button>

        <div className="section-title">Conversations</div>
        <div className="chat-list">
          {chats.map((chat) => (
            <button
              key={chat.id}
              className={`chat-item ${chat.id === seriesId ? "active" : ""}`}
              onClick={() => openChat(chat.id)}
              disabled={busy}
            >
              {chat.title}
            </button>
          ))}
        </div>

        <div className="section-title">
          Family agents <span className="live">● LIVE</span>
        </div>
        <div className="family-list">
          {family === null && <div className="muted">Loading…</div>}
          {family?.length === 0 && (
            <div className="muted">No family nodes in the federation yet.</div>
          )}
          {family?.map((node) => {
            const online = node.status.toLowerCase() === "online";
            return (
              <div key={node.name} className="member">
                <div className="avatar">{node.name[0]}</div>
                <div className="member-text">
                  <div className="member-name">{node.name}</div>
                  <div className="member-sub">SuperNode · {node.status}</div>
                </div>
                <span className={`dot ${online ? "on" : ""}`} />
              </div>
            );
          })}
        </div>

        <div className="privacy">
          🔒 Calendars stay on each laptop. Only replies travel over Flower.
        </div>
      </aside>

      <main className="main">
        <header className="header">
          <div className="title">Plan with your family</div>
          <div className="subtitle">Ask about schedules and appointments</div>
        </header>

        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">Ask a question to start a conversation.</div>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="user-msg">
                {m.text}
              </div>
            ) : (
              <div key={i} className="bot-msg">
                <div className="bot-avatar">F</div>
                <div className="bot-body">
                  {m.text && <Markdown>{m.text}</Markdown>}
                  {m.status && (
                    <div className="status">
                      <span className="spinner" /> {m.status}
                    </div>
                  )}
                  {m.error && <div className="error">Error: {m.error}</div>}
                </div>
              </div>
            ),
          )}
          <div ref={bottomRef} />
        </div>

        <div className="composer-wrap">
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask to find a time…"
              disabled={busy}
            />
            <button type="submit" disabled={busy || !input.trim()} aria-label="Send">
              ➤
            </button>
          </form>
          <div className="hint">Try: “When is everyone free this Saturday?”</div>
        </div>
      </main>
    </div>
  );
}
