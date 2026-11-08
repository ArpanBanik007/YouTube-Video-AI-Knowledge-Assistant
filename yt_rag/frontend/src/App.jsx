import { useState, useRef, useEffect } from "react";
import "./App.css";

const API = "http://localhost:8000";

const SUGGESTIONS = [
  "What is RAG?",
  "RAG kya hota hai?",
  "Machine learning kya hai?",
  "What is the capital of Japan?",
];

const STEPS = [
  "Searching video transcripts",
  "Ranking the most relevant moments",
  "Generating answer",
];

const Icon = {
  play: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
  ),
  external: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 3h7v7M10 14L21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" /></svg>
  ),
  close: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 6L6 18M6 6l12 12" /></svg>
  ),
  send: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4z" /></svg>
  ),
  check: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6L9 17l-5-5" /></svg>
  ),
};

function renderAnswer(text, sources, onPlay) {
  const map = Object.fromEntries(sources.map((s) => [s.n, s]));
  return text.split(/(\*\*[^*]+\*\*|\[\d+\])/g).map((part, i) => {
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite && map[cite[1]]) {
      const s = map[cite[1]];
      return (
        <button
          key={i}
          className="cite"
          onClick={() => onPlay(s)}
          title={`${s.title} @ ${s.timestamp}`}
        >
          {cite[1]}
        </button>
      );
    }
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) return <strong key={i}>{bold[1]}</strong>;
    return <span key={i}>{part}</span>;
  });
}

function Loader({ step }) {
  return (
    <div className="msg bot loader">
      <ul className="steps">
        {STEPS.map((label, i) => (
          <li key={label} className={i < step ? "done" : i === step ? "active" : ""}>
            <span className="step-icon">
              {i < step ? Icon.check : i === step ? <span className="spinner" /> : null}
            </span>
            {label}
            {i === step && <span className="dots" />}
          </li>
        ))}
      </ul>
      <div className="skeleton">
        <div className="line w90" />
        <div className="line w75" />
        <div className="line w60" />
      </div>
    </div>
  );
}

function Player({ active, onClose }) {
  if (!active) {
    return (
      <div className="player-empty">
        <div className="empty-icon">{Icon.play}</div>
        <h3>Video player</h3>
        <p>Answer-er kono timestamp ba source card-e click korle video ekhane exact oi moment theke chalbe.</p>
      </div>
    );
  }
  const embed = `https://www.youtube.com/embed/${active.video_id}?start=${active.start}&autoplay=1&rel=0`;
  return (
    <div className="player">
      <div className="player-head">
        <div className="player-title">
          <span className="player-time">{active.timestamp}</span>
          <span className="ellipsis">{active.title}</span>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close player">{Icon.close}</button>
      </div>
      <div className="frame">
        <iframe
          key={`${active.video_id}-${active.start}`}
          src={embed}
          title={active.title}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
      <div className="player-actions">
        <a className="btn primary" href={active.url} target="_blank" rel="noreferrer">
          {Icon.external} Open on YouTube
        </a>
        <span className="hint">Video na challe (embed blocked), upore button diye YouTube-e dekho.</span>
      </div>
      {active.text && (
        <div className="snippet">
          <div className="snippet-label">Transcript excerpt</div>
          <p>{active.text}…</p>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState(0);
  const [active, setActive] = useState(null);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, step]);

  useEffect(() => {
    if (!loading) return;
    setStep(0);
    const id = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 1100);
    return () => clearInterval(id);
  }, [loading]);

  async function send(question) {
    const q = question.trim();
    if (!q || loading) return;
    setMessages((m) => [...m, { role: "user", text: q }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Server error");
      setMessages((m) => [...m, { role: "bot", ...data }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "bot", error: e.message, sources: [] }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={`shell ${active ? "has-player" : ""}`}>
      <section className="chat">
        <header className="topbar">
          <div className="logo">▶</div>
          <div>
            <h1>YouTube Knowledge Assistant</h1>
            <p>Semantic search across your playlist with timestamp-accurate answers</p>
          </div>
        </header>

        <main>
          {messages.length === 0 && !loading && (
            <div className="welcome">
              <h2>Ki jante chao?</h2>
              <p>English, Hindi ba Hinglish-e jiggasa koro. Answer-er sathe video-r exact moment paabe.</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)}>{s}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="msg user">{m.text}</div>
            ) : (
              <div key={i} className="msg bot">
                {m.error ? (
                  <div className="error">{m.error}</div>
                ) : (
                  <>
                    <div className="answer">{renderAnswer(m.answer, m.sources, setActive)}</div>
                    {m.provider && (
                      <div className="meta">Answered by {m.provider} in {m.seconds}s</div>
                    )}
                    {m.sources.length > 0 && (
                      <div className="sources">
                        <div className="sources-label">Sources</div>
                        {m.sources.map((s) => (
                          <div
                            key={s.n}
                            className={`source ${active && active.video_id === s.video_id && active.start === s.start ? "selected" : ""}`}
                          >
                            <button className="source-main" onClick={() => setActive(s)}>
                              <div className="src-top">
                                <span className="badge">{s.n}</span>
                                <span className="time">{Icon.play} {s.timestamp}</span>
                                <span className="score">match {Math.round(s.score * 100)}%</span>
                              </div>
                              <div className="src-title">{s.title}</div>
                              <div className="src-text">{s.text}…</div>
                            </button>
                            <a
                              className="open-ext"
                              href={s.url}
                              target="_blank"
                              rel="noreferrer"
                              title="Open on YouTube in a new tab"
                            >
                              {Icon.external}
                            </a>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            )
          )}

          {loading && <Loader step={step} />}
          <div ref={bottomRef} />
        </main>

        <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything about the videos..."
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()} aria-label="Send">
            {Icon.send}
          </button>
        </form>
      </section>

      <aside className="side">
        <Player active={active} onClose={() => setActive(null)} />
      </aside>
    </div>
  );
}