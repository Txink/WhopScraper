import type React from "react";
import { paletteColorFor } from "./avatarPalette";

export interface MessageShellProps {
  sender: string;
  firstAt: string;
  avatarColor?: string;
  avatarText?: string;
  align: "left" | "right";
  senderTone?: "stock" | "option";
  /** When true, render the avatar with .chat-avatar-neutral (gray bg + fg-2
   *  text) instead of a per-name palette color. Used in highlight mode for
   *  non-watched senders so the watched ones visually pop. */
  dim?: boolean;
  children: React.ReactNode;
}

// Local-time HH:mm formatter. Duplicates same logic in ChatCard.tsx —
// keep behavior in sync or extract to a shared util in a follow-up.
function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function MessageShell({
  sender,
  firstAt,
  avatarColor,
  avatarText,
  align,
  senderTone,
  dim,
  children,
}: MessageShellProps): JSX.Element {
  const cls = [
    "chat-group",
    align === "right" ? "chat-group--right" : null,
    senderTone === "stock" ? "monitor stock" : null,
    senderTone === "option" ? "monitor option" : null,
  ]
    .filter(Boolean)
    .join(" ");

  const avatarCls = dim ? "chat-avatar chat-avatar-neutral" : "chat-avatar";
  const avatarStyle: React.CSSProperties | undefined = dim
    ? undefined
    : { background: avatarColor ?? paletteColorFor(sender) };
  const txt = avatarText ?? sender.slice(-1);

  return (
    <div className={cls} data-sender={sender}>
      <div className="chat-group-head">
        <span className={avatarCls} style={avatarStyle}>
          {txt}
        </span>
        <span className="chat-group-author">{sender}</span>
        <span className="chat-group-time">{fmtTime(firstAt)}</span>
      </div>
      <div className="chat-group-body">{children}</div>
    </div>
  );
}
