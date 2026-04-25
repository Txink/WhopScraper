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
    const urls: (string | null)[] = [];
    const seen = new Set<string | null>();
    for (const t of orphanTasks) {
      const u = t.message?.url ?? null;
      if (!seen.has(u)) {
        seen.add(u);
        urls.push(u);
      }
    }
    return urls;
  }, [orphanTasks]);

  const total = orphanTasks.length;
  const cleanableUrlCount = distinctUrls.length;
  const nullUrlCount = orphanTasks.filter(t => !t.message?.url).length;

  if (total === 0) return null;

  const handleCleanupAll = async () => {
    // null url is now a valid cleanup target — no early disable.
    const msg = nullUrlCount > 0 && cleanableUrlCount > 1
      ? `确认从数据库删除全部 ${total} 条已停用任务？\n（其中 ${nullUrlCount} 条为 url 缺失的旧数据。）\n此操作不可逆。`
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
          const label = url ?? "(legacy null url)";
          failed.push(label);
          console.warn("cleanup failed for", label, e);
        }
      }
      if (failed.length > 0) {
        const detail = failed.slice(0, 3).join(", ") + (failed.length > 3 ? "…" : "");
        setError(`已清理 ${deletedTotal} 条；${failed.length} 个分组失败：${detail}`);
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
        {cleanableUrlCount > 0 && (
          <span className="dim">
            （{cleanableUrlCount} 个 url 来源{nullUrlCount > 0 ? "，含旧数据" : ""}）
          </span>
        )}
      </div>
      <button
        onClick={handleCleanupAll}
        disabled={busy}
        className="orphan-cleanup-btn"
      >
        {busy ? "清理中…" : "🗑 清理全部"}
      </button>
      {error && <div className="orphan-cleanup-error">{error}</div>}
    </div>
  );
}
