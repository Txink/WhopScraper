import type { WhopPage } from "../../api/domain-types";

interface Props {
  page: WhopPage | null;
  mode: "page" | "orphan";
  orphanCount?: number;
  newMessageCount?: number;
  onJumpToCurrent?: () => void;
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "—";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(0)}s 前`;
  if (s < 3600) return `${(s / 60).toFixed(0)}m 前`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h 前`;
  return `${(s / 86400).toFixed(1)}d 前`;
}

export function PageInfoBar({
  page,
  mode,
  orphanCount = 0,
  newMessageCount,
  onJumpToCurrent,
}: Props) {
  if (mode === "orphan") {
    return (
      <div className="page-info-bar orphan">
        <span className="badge gray">已停用</span>
        <span>共 {orphanCount} 条历史 task — 来源 page 已被移除</span>
      </div>
    );
  }
  if (!page) return null;

  const showNewBadge = (newMessageCount ?? 0) > 0 && onJumpToCurrent != null;

  return (
    <div className="page-info-bar">
      <div className="page-info-row">
        <span className={`badge ${page.source}`}>{page.source === "stock" ? "正股" : "期权"}</span>
        <span className="page-name">{page.name}</span>
        <span className="sep">·</span>
        <span>最后轮询 {formatRelative(page.last_poll_at)}</span>
        <span className="sep">·</span>
        {showNewBadge ? (
          <button
            type="button"
            className="page-info-new-msg"
            onClick={onJumpToCurrent}
          >
            新消息 +{newMessageCount}
          </button>
        ) : (
          <span>已发消息 {page.messages_published}</span>
        )}
      </div>
      <a
        className="page-url"
        href={page.url}
        target="_blank"
        rel="noopener noreferrer"
        title={page.url}
      >
        {page.url}
      </a>
    </div>
  );
}
