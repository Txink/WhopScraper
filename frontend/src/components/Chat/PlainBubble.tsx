import type React from "react";

export interface PlainBubbleProps {
  content: string;
  quoted?: { author: string; content: string } | null;
}

export function PlainBubble({ content, quoted }: PlainBubbleProps): JSX.Element {
  return (
    <div className="chat-group-bubble">
      {quoted && (
        <div className="chat-group-quoted" title={quoted.content}>
          <span className="chat-group-quoted-sender">{quoted.author}</span>
          <span className="chat-group-quoted-body">{quoted.content}</span>
        </div>
      )}
      {content}
    </div>
  );
}
