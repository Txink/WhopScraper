interface Props {
  messageCount: number;
  watchedCount: number;
  onExport: () => void;
}

export function ChatMetaBar({ messageCount, watchedCount, onExport }: Props) {
  return (
    <div className="chat-meta-bar">
      <span className="chat-meta-text">
        本周抓取 <strong>{messageCount}</strong> 条
        · 关注 <strong>{watchedCount}</strong> 位发送者
      </span>
      <button className="chat-meta-export" onClick={onExport} type="button">
        导出 JSON
      </button>
    </div>
  );
}
