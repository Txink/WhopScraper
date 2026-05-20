import type { ChatMessageOut } from "./chatCards";
import { MessageShell } from "./MessageShell";
import { PlainBubble } from "./PlainBubble";

export interface ChatMessageProps {
  sender: string;
  firstAt: string;
  messages: ChatMessageOut[];
  align: "left" | "right";
}

export function ChatMessage({
  sender, firstAt, messages, align,
}: ChatMessageProps): JSX.Element {
  return (
    <MessageShell sender={sender} firstAt={firstAt} align={align}>
      {messages.map((m) => (
        <PlainBubble key={m.id} content={m.content} quoted={m.quoted ?? null} />
      ))}
    </MessageShell>
  );
}
