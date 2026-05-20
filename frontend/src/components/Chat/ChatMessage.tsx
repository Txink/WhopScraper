import type { ChatMessageOut } from "./chatCards";
import { MessageShell } from "./MessageShell";
import { PlainBubble } from "./PlainBubble";

export interface ChatMessageProps {
  sender: string;
  firstAt: string;
  messages: ChatMessageOut[];
  align: "left" | "right";
  /** Dim the avatar (gray) for non-watched senders in highlight mode.
   *  Passed through to MessageShell. */
  dim?: boolean;
}

export function ChatMessage({
  sender, firstAt, messages, align, dim,
}: ChatMessageProps): JSX.Element {
  return (
    <MessageShell sender={sender} firstAt={firstAt} align={align} dim={dim}>
      {messages.map((m) => (
        <PlainBubble key={m.id} content={m.content} quoted={m.quoted ?? null} />
      ))}
    </MessageShell>
  );
}
