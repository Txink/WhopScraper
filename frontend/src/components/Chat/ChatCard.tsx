import { paletteColorFor } from "./avatarPalette";
import { authedAssetUrl } from "../../api/http";
import {
  watchedCount,
  type BatchItem,
  type ChatCard as ChatCardData,
  type ChatMessageOut,
} from "./chatCards";

interface Props {
  card: ChatCardData;
}

/** A run of consecutive items inside a card that share the same author
 *  AND kind — rendered as one chat-group block (matching the highlight
 *  mode visual: avatar + author head, followed by 1+ bubbles). */
interface Block {
  kind: "watched" | "context";
  author: string;
  firstAt: string;
  msgs: ChatMessageOut[];
}

function buildBlocks(items: BatchItem[]): Block[] {
  const blocks: Block[] = [];
  for (const it of items) {
    const last = blocks[blocks.length - 1];
    if (last && last.author === it.msg.author && last.kind === it.kind) {
      last.msgs.push(it.msg);
    } else {
      blocks.push({
        kind: it.kind,
        author: it.msg.author,
        firstAt: it.msg.posted_at,
        msgs: [it.msg],
      });
    }
  }
  return blocks;
}

export function ChatCard({ card }: Props): JSX.Element {
  const blocks = buildBlocks(card.items);
  const lastTs = card.items[card.items.length - 1]?.msg.posted_at ?? "";

  return (
    <div className="chat-card" data-kind={card.kind}>
      <div className="chat-card-head">
        <span
          className="chat-avatar"
          style={{ background: paletteColorFor(card.target_author) }}
        >
          {card.target_author.slice(-1)}
        </span>
        <span className="chat-card-sender">{card.target_author}</span>
        <span className="chat-card-msg-count">{watchedCount(card)}</span>
        <span className="chat-card-time">{fmtTime(lastTs)}</span>
      </div>
      <div className="chat-card-body">
        {blocks.map((b, i) => renderBlock(b, i))}
      </div>
    </div>
  );
}

function renderBlock(b: Block, idx: number): JSX.Element {
  const isWatched = b.kind === "watched";
  const avatarStyle: React.CSSProperties | undefined = isWatched
    ? { background: paletteColorFor(b.author) }
    : undefined;
  const avatarCls = isWatched
    ? "chat-avatar"
    : "chat-avatar chat-avatar-neutral";
  return (
    <div
      key={`${idx}-${b.msgs[0].id}`}
      className={`chat-group${isWatched ? " chat-group--right" : ""}`}
    >
      <div className="chat-group-head">
        <span className={avatarCls} style={avatarStyle}>
          {b.author.slice(-1)}
        </span>
        <span className="chat-group-author">{b.author}</span>
        <span className="chat-group-time">{fmtTime(b.firstAt)}</span>
      </div>
      <div className="chat-group-body">
        {b.msgs.map((m) => {
          const imageOnly = !!m.image_url && m.content.length === 0;
          const cls = imageOnly
            ? "chat-group-bubble chat-group-bubble--image-only"
            : "chat-group-bubble";
          return (
            <div key={m.id} className={cls}>
              {m.quoted && (
                <div className="chat-group-quoted" title={m.quoted.content}>
                  <span className="chat-group-quoted-sender">
                    {m.quoted.author}
                  </span>
                  <span className="chat-group-quoted-body">
                    {m.quoted.content}
                  </span>
                </div>
              )}
              {m.image_url && (
                <img
                  className="chat-group-image"
                  src={authedAssetUrl(m.image_url)}
                  alt=""
                />
              )}
              {m.content}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function fmtTime(iso: string): string {
  // Backend serializes UTC posted_at as naive ISO; force UTC parse before
  // letting the browser apply its local offset. Mirrors MessageShell.fmtTime.
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
