import type { ChatMessageOut } from "./chatCards";

interface Props {
  messages: ChatMessageOut[];
  /** When provided + non-empty, blocks whose author is in this set render
   *  with the brand-colored avatar; others get the neutral avatar.
   *  Used by "关注模式" — full chat stream with watched senders' icons
   *  tinted. Omit / empty set → all avatars use the brand color (legacy
   *  group-chat appearance, unchanged). */
  watched?: Set<string>;
}

interface Block {
  id: string;
  author: string;
  firstAt: string;
  msgs: ChatMessageOut[];
}

export function GroupChatView({ messages, watched }: Props): JSX.Element {
  const blocks: Block[] = [];
  for (const m of messages) {
    const last = blocks[blocks.length - 1];
    if (last && last.author === m.author) {
      last.msgs.push(m);
    } else {
      blocks.push({ id: m.id, author: m.author, firstAt: m.posted_at, msgs: [m] });
    }
  }

  const tinting = watched !== undefined && watched.size > 0;
  const avatarFor = (author: string): { cls: string; style?: React.CSSProperties } => {
    if (!tinting) return { cls: "chat-avatar chat-avatar-target" };
    if (!watched!.has(author)) return { cls: "chat-avatar chat-avatar-neutral" };
    // Watched in highlight mode → deterministic palette color per name.
    return { cls: "chat-avatar", style: { background: paletteColorFor(author) } };
  };

  return (
    <>
      {blocks.map((b) => {
        const av = avatarFor(b.author);
        const isWatchedBlock = tinting && watched!.has(b.author);
        return (
        <div key={b.id} className={`chat-group${isWatchedBlock ? " chat-group--right" : ""}`}>
          <div className="chat-group-head">
            <span className={av.cls} style={av.style}>
              {b.author.slice(-1)}
            </span>
            <span className="chat-group-author">{b.author}</span>
            <span className="chat-group-time">{fmtTime(b.firstAt)}</span>
          </div>
          <div className="chat-group-body">
            {b.msgs.map((m) => (
              <div key={m.id} className="chat-group-bubble">
                {m.quoted && (
                  <div className="chat-group-quoted" title={m.quoted.content}>
                    <span className="chat-group-quoted-sender">{m.quoted.author}</span>
                    <span className="chat-group-quoted-body">{m.quoted.content}</span>
                  </div>
                )}
                {m.content}
              </div>
            ))}
          </div>
        </div>
        );
      })}
    </>
  );
}

/** 8-color palette covering the saturated end of the project's accent
 *  tokens (brand cyan, ok green, info blue, warn amber, plus purple /
 *  red / orange / teal) so each watched sender gets a distinct avatar
 *  background in 关注模式. Color choice is a deterministic hash of the
 *  author's name — same name always gets the same color across renders
 *  and sessions. */
const AVATAR_PALETTE = [
  "#3fb5c5", // brand cyan
  "#3dd68c", // ok green
  "#5aa0ff", // info blue
  "#e7a73d", // warn amber
  "#c688ff", // purple (option-type accent)
  "#ef5b5b", // err red
  "#ff8c52", // orange
  "#5fd1c1", // teal
];

function paletteColorFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

function fmtTime(iso: string): string {
  // Backend stores UTC but Pydantic serializes the SQLite-native naive
  // datetime without a "Z"/offset suffix. Browsers vary on how they
  // parse those — some treat naive ISO as local time, which made a
  // Beijing-22:59 message render as 14:59 (the UTC hour shown as if it
  // were local). Force UTC by appending "Z" when no TZ designator is
  // present; getHours() then applies the browser's local offset.
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
