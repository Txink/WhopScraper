import type { WhopPage } from "../../api/domain-types";

interface Props {
  page: WhopPage | null;   // null = orphan
  orphanCount?: number;
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

export function PageInfoBar({ page, orphanCount = 0 }: Props) {
  if (page === null) {
    return (
      <div className="page-info-bar orphan">
        <span className="badge gray">已停用</span>
        <span>共 {orphanCount} 条历史 task — 来源 page 已被移除</span>
      </div>
    );
  }
  // Note: running/stopped/error status moved to the power-button in PageActionBar.
  // URL goes on its own line below the meta row so long urls show fully (wrap on long).
  return (
    <div className="page-info-bar">
      <div className="page-info-row">
        <span className={`badge ${page.source}`}>{page.source === "stock" ? "正股" : "期权"}</span>
        <span className="page-name">{page.name}</span>
        <span className="sep">·</span>
        <span>最后轮询 {formatRelative(page.last_poll_at)}</span>
        <span className="sep">·</span>
        <span>已发消息 {page.messages_published}</span>
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
