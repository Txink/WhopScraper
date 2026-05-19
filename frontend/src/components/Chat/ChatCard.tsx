import type { ChatCard as ChatCardData } from "./chatCards";

interface Props {
  card: ChatCardData;
}

export function ChatCard({ card }: Props): JSX.Element {
  if (card.kind === "quote") {
    return (
      <div className="chat-card" data-kind="quote">
        <div className="chat-card-head">
          <span className="chat-avatar chat-avatar-target">
            {card.target.author.slice(-1)}
          </span>
          <span className="chat-card-sender">{card.target.author}</span>
          <span className="chat-card-badge">引用</span>
          <span className="chat-card-time">
            {fmtTime(card.target.posted_at)}
          </span>
        </div>
        <div className="chat-thread">
          <div className="chat-row chat-row-left">
            <span className="chat-avatar-sm">
              {card.quoted.author.slice(-1)}
            </span>
            <div className="chat-bubble chat-bubble-left">
              <div>{card.quoted.content}</div>
              <div className="chat-bubble-meta">
                <span className="chat-sender-tag">{card.quoted.author}</span>
                {card.quoted.posted_at && (
                  <span>{fmtTime(card.quoted.posted_at)}</span>
                )}
              </div>
            </div>
          </div>
          <div className="chat-row chat-row-right">
            <div className="chat-bubble chat-bubble-right">
              <div>{card.target.content}</div>
              <div className="chat-bubble-meta">
                <span>{fmtTime(card.target.posted_at)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-card" data-kind="batch">
      <div className="chat-card-head">
        <span className="chat-avatar chat-avatar-target">
          {card.target_author.slice(-1)}
        </span>
        <span className="chat-card-sender">{card.target_author}</span>
        <span className="chat-card-msg-count">{card.msgs.length}</span>
        <span className="chat-card-time">
          {fmtTime(card.msgs[card.msgs.length - 1].posted_at)}
        </span>
      </div>
      <div className="chat-thread">
        {card.msgs.map((m) => (
          <div key={m.id} className="chat-row chat-row-right">
            <div className="chat-bubble chat-bubble-right">
              <div>{m.content}</div>
              <div className="chat-bubble-meta">
                <span>{fmtTime(m.posted_at)}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function fmtTime(iso: string): string {
  // See GroupChatView.fmtTime — backend serializes UTC posted_at as naive
  // ISO; force UTC parse before letting the browser apply its local offset.
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
