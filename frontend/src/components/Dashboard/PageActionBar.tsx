import { useState } from "react";
import { api } from "../../api/http";
import { usePageTabsStore } from "../../stores/pageTabs";
import type { WhopPage } from "../../api/domain-types";

interface Props {
  page: WhopPage | null;            // null = orphan
  onOpenSettings: () => void;
}

export function PageActionBar({ page, onOpenSettings }: Props) {
  const [restarting, setRestarting] = useState(false);
  const isOrphan = page === null;
  const tabId = isOrphan ? "orphan" : page!.id;
  const expandMode = usePageTabsStore(s => s.expandModeByTab[tabId] ?? "smart");
  const setExpand = usePageTabsStore(s => s.setExpandMode);

  const handleRestart = async () => {
    if (isOrphan) return;
    if (!confirm(`确认重启 "${page!.name}"？`)) return;
    setRestarting(true);
    try { await api.restartWhopPage(page!.id); }
    catch (e) { alert(`重启失败：${e instanceof Error ? e.message : e}`); }
    finally { setRestarting(false); }
  };

  return (
    <div className="page-action-bar">
      <button onClick={handleRestart} disabled={isOrphan || restarting} className="action-btn">
        {restarting ? "重启中…" : "↻ 重启"}
      </button>
      <button onClick={onOpenSettings} disabled={isOrphan} className="action-btn">
        ⚙ 设置
      </button>
      <span className="spacer" />
      <button
        onClick={() => setExpand(tabId, "all-open")}
        className={expandMode === "all-open" ? "action-btn active" : "action-btn"}
      >⤓ 全展开</button>
      <button
        onClick={() => setExpand(tabId, "all-closed")}
        className={expandMode === "all-closed" ? "action-btn active" : "action-btn"}
      >⤒ 全收缩</button>
      {expandMode !== "smart" && (
        <button onClick={() => setExpand(tabId, "smart")} className="action-btn link">
          回 smart
        </button>
      )}
    </div>
  );
}
