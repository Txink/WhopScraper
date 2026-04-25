import { useState, useMemo } from "react";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import type { TaskSummary } from "../../api/domain-types";

interface Props {
  orphanTasks: TaskSummary[];
}

export function OrphanCleanupBar({ orphanTasks }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const distinctUrls = useMemo(() => {
    const s = new Set<string>();
    for (const t of orphanTasks) {
      const u = t.message?.url;
      if (u) s.add(u);
    }
    return Array.from(s);
  }, [orphanTasks]);

  const total = orphanTasks.length;
  const cleanableUrlCount = distinctUrls.length;
  const nullUrlCount = orphanTasks.filter(t => !t.message?.url).length;

  if (total === 0) return null;

  const handleCleanupAll = async () => {
    if (cleanableUrlCount === 0) {
      alert("所有已停用任务的 url 都缺失（migration 前数据），无法按 url 清理。");
      return;
    }
    const msg = nullUrlCount > 0
      ? `确认从数据库删除 ${total - nullUrlCount} 条已停用任务？\n（另有 ${nullUrlCount} 条 url 缺失的旧数据无法清理。）\n此操作不可逆。`
      : `确认从数据库删除全部 ${total} 条已停用任务？\n此操作不可逆。`;
    if (!confirm(msg)) return;

    setBusy(true);
    setError(null);
    let deletedTotal = 0;
    const failed: string[] = [];
    try {
      for (const url of distinctUrls) {
        try {
          const r = await api.cleanupOrphanByUrl(url);
          deletedTotal += r.deleted_count;
          useTasksStore.getState().removeTasksByUrl(url);
        } catch (e) {
          failed.push(url);
          console.warn("cleanup failed for", url, e);
        }
      }
      if (failed.length > 0) {
        const detail = failed.slice(0, 3).join(", ") + (failed.length > 3 ? "…" : "");
        setError(`已清理 ${deletedTotal} 条；${failed.length} 个 url 失败：${detail}`);
      }
    } catch (e) {
      setError(e instanceof HttpError ? e.message : (e instanceof Error ? e.message : String(e)));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="orphan-cleanup-bar">
      <div className="orphan-cleanup-summary">
        <span>已停用任务共 {total} 条</span>
        {cleanableUrlCount > 0 && <span className="dim">（{cleanableUrlCount} 个 url 来源）</span>}
        {nullUrlCount > 0 && (
          <span className="dim">· {nullUrlCount} 条 url 缺失（旧数据，无法清理）</span>
        )}
      </div>
      <button
        onClick={handleCleanupAll}
        disabled={busy || cleanableUrlCount === 0}
        className="orphan-cleanup-btn"
      >
        {busy ? "清理中…" : "🗑 清理全部"}
      </button>
      {error && <div className="orphan-cleanup-error">{error}</div>}
    </div>
  );
}
