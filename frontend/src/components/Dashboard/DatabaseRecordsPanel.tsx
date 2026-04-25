import { useEffect, useMemo, useState } from "react";
import type { TaskSummary } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";

const PAGE_SIZE = 15;

function fmtTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

function getMessageTime(task: TaskSummary): string {
  return task.message.posted_at || task.message.received_at || task.created_at;
}

interface Props {
  pageNameByUrl: Map<string, string>;
}

export function DatabaseRecordsPanel({ pageNameByUrl }: Props) {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageRows, setPageRows] = useState<Record<number, TaskSummary[]>>({});
  const [pageCursor, setPageCursor] = useState<Record<number, string | null>>({ 1: null });
  const [pageNextCursor, setPageNextCursor] = useState<Record<number, string | null>>({});
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPage = async (page: number, force = false) => {
    if (!force && pageRows[page]) return;
    const cursor = pageCursor[page];
    if (cursor === undefined) return;

    setLoading(true);
    setError(null);
    try {
      const [r, c] = await Promise.all([
        api.listTasks(cursor ? { limit: PAGE_SIZE, cursor } : { limit: PAGE_SIZE }),
        api.countTasks(),
      ]);
      const nextCursor = r.next_cursor ?? null;
      setPageRows((prev) => ({ ...prev, [page]: r.tasks }));
      setPageNextCursor((prev) => ({ ...prev, [page]: nextCursor }));
      setTotalCount(c.total_count);
      if (nextCursor !== null) {
        setPageCursor((prev) => (prev[page + 1] !== undefined ? prev : { ...prev, [page + 1]: nextCursor }));
      }
    } catch (e) {
      if (e instanceof HttpError) {
        setError(e.message);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPage(currentPage);
  }, [currentPage]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = async () => {
    await loadPage(currentPage, true);
  };

  const records = pageRows[currentPage] ?? [];
  const hasPrev = currentPage > 1;
  const hasNext = pageNextCursor[currentPage] != null;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const rows = useMemo(
    () =>
      records.map((task) => {
        const sourceUrl = task.message.url;
        const pageName = sourceUrl ? pageNameByUrl.get(sourceUrl) : null;
        const sourceState = sourceUrl == null ? "missing" : pageName ? "active" : "orphan";
        const sourceLabel =
          sourceState === "active"
            ? pageName!
            : sourceState === "orphan"
              ? "已移除页面"
              : "无来源";
        return { task, sourceState, sourceLabel };
      }),
    [records, pageNameByUrl],
  );

  return (
    <section className="db-panel" aria-label="数据库记录">
      <header className="db-panel-head">
        <div className="db-panel-title-wrap">
          <h3>数据库记录</h3>
          <p>按页查看持久化 task 记录（每页 15 条）</p>
        </div>
        <button className="db-refresh-btn" onClick={refresh} disabled={loading}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </header>

      {error && <div className="db-error">{error}</div>}

      {!loading && rows.length === 0 ? (
        <div className="empty-state">
          <p>数据库中暂无记录。</p>
        </div>
      ) : (
        <div className="db-table-wrap">
          <table className="db-table">
            <thead>
              <tr>
                <th>消息时间</th>
                <th>来源页</th>
                <th>状态</th>
                <th>作者</th>
                <th>摘要</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ task, sourceState, sourceLabel }) => (
                <tr key={task.id}>
                  <td>{fmtTime(getMessageTime(task))}</td>
                  <td>
                    <span className={`db-source ${sourceState}`}>
                      {sourceLabel}
                    </span>
                  </td>
                  <td className={`db-status ${task.status.toLowerCase()}`}>{task.status}</td>
                  <td>{task.message.author ?? "—"}</td>
                  <td className="db-content">{task.message.content}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer className="db-pagination">
        <button
          className="db-page-btn"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={loading || !hasPrev}
        >
          上一页
        </button>
        <span className="db-page-indicator">第 {currentPage} 页 / 共 {totalPages} 页</span>
        <button
          className="db-page-btn"
          onClick={() => setCurrentPage((p) => p + 1)}
          disabled={loading || !hasNext}
        >
          下一页
        </button>
      </footer>
    </section>
  );
}
