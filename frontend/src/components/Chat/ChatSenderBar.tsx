import { patchWatchedSenders } from "../../api/chat";

interface Author { name: string; count: number; }

interface Props {
  pageId: string;
  authors: Author[];
  watchedSenders: string[];
  onChange: (next: string[]) => void;
}

export function ChatSenderBar({ pageId, authors, watchedSenders, onChange }: Props) {
  const watched = new Set(watchedSenders);
  async function toggle(name: string) {
    const next = watched.has(name)
      ? watchedSenders.filter((s) => s !== name)
      : [...watchedSenders, name];
    onChange(next);
    try { await patchWatchedSenders(pageId, next); } catch { /* surfaced via store later */ }
  }

  return (
    <div className="chat-sender-bar">
      <span className="chat-sender-bar-label">发送者</span>
      {authors.map((a) => {
        const on = watched.has(a.name);
        return (
          <button
            key={a.name}
            className={`chat-sender-chip${on ? " on" : ""}`}
            onClick={() => toggle(a.name)}
            type="button"
          >
            <span className="chat-sender-chip-avatar">{a.name.slice(-1)}</span>
            {a.name}
            <span className="chat-sender-chip-count">· {a.count}</span>
          </button>
        );
      })}
    </div>
  );
}
