import { useState, useMemo } from "react";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import type { TaskSummary } from "../../api/domain-types";

interface Props {
  orphanTasks: TaskSummary[];
}

interface UrlGroup {
  url: string; // empty string for url=null tasks
  count: number;
}

export function OrphanCleanupBar({ orphanTasks }: Props) {
  const [busy, setBusy] = useState<string | null>(null); // url currently being deleted
  const [error, setError] = useState<string | null>(null);

  const groups: UrlGroup[] = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of orphanTasks) {
      const u = t.message?.url ?? "";
      m.set(u, (m.get(u) ?? 0) + 1);
    }
    return Array.from(m.entries())
      .map(([url, count]) => ({ url, count }))
      .sort((a, b) => b.count - a.count);
  }, [orphanTasks]);

  if (groups.length === 0) return null;

  const handleRemove = async (url: string, count: number) => {
    if (!url) {
      // url=null tasks (very old data) — can't be addressed by url; show explainer
      alert("这些任务的来源 url 缺失（migration 前数据），无法按 url 清理。");
      return;
    }
    if (!confirm(`确认从数据库删除 ${count} 条来自 "${url}" 的历史任务？此操作不可逆。`)) return;
    setBusy(url);
    setError(null);
    try {
      await api.cleanupOrphanByUrl(url);
      // Local store update — drop tasks for this url
      useTasksStore.getState().removeTasksByUrl(url);
    } catch (e) {
      if (e instanceof HttpError) {
        const detail =
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail)
            : e.message;
        setError(detail);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="orphan-cleanup-bar">
      <div className="orphan-cleanup-hint">
        已停用任务按 url 分组，可逐组从数据库彻底清理：
      </div>
      <ul className="orphan-cleanup-list">
        {groups.map((g) => (
          <li key={g.url || "__null__"}>
            <code className="orphan-url" title={g.url || "(无 url 的旧数据)"}>
              {g.url || "(无 url)"}
            </code>
            <span className="orphan-count">{g.count} 条</span>
            <button
              onClick={() => handleRemove(g.url, g.count)}
              disabled={busy === g.url}
              className="orphan-remove-btn"
            >
              {busy === g.url ? "删除中…" : "移除"}
            </button>
          </li>
        ))}
      </ul>
      {error && <div className="orphan-cleanup-error">{error}</div>}
    </div>
  );
}
