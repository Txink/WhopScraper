import { authedAssetUrl } from "../../api/http";

export interface PlainBubbleProps {
  content: string;
  quoted?: { author: string; content: string } | null;
  imageUrl?: string | null;
}

export function PlainBubble({
  content, quoted, imageUrl,
}: PlainBubbleProps): JSX.Element {
  const imageOnly = !!imageUrl && content.length === 0;
  const cls = imageOnly
    ? "chat-group-bubble chat-group-bubble--image-only"
    : "chat-group-bubble";
  return (
    <div className={cls}>
      {quoted && (
        <div className="chat-group-quoted" title={quoted.content}>
          <span className="chat-group-quoted-sender">{quoted.author}</span>
          <span className="chat-group-quoted-body">{quoted.content}</span>
        </div>
      )}
      {imageUrl && (
        <img className="chat-group-image" src={authedAssetUrl(imageUrl)} alt="" />
      )}
      {content}
    </div>
  );
}
