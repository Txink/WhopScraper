import { useState } from "react";
import { api } from "../../api/http";
import { usePageTabsStore } from "../../stores/pageTabs";
import type { ExpandMode } from "../../stores/pageTabs";
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

  const cycleExpandMode = () => {
    const next: ExpandMode =
      expandMode === "smart" ? "all-open"
      : expandMode === "all-open" ? "all-closed"
      : "smart";
    setExpand(tabId, next);
  };

  const expandLabel =
    expandMode === "smart" ? "◐ 智能展开"
    : expandMode === "all-open" ? "▽ 全部展开"
    : "△ 全部收起";

  const expandTitle =
    expandMode === "smart" ? "智能展开 — 点击切换为全部展开"
    : expandMode === "all-open" ? "全部展开 — 点击切换为全部收起"
    : "全部收起 — 点击回到智能模式";

  return (
    <div className="page-action-bar">
      <button onClick={handleRestart} disabled={isOrphan || restarting} className="action-btn">
        {restarting ? "重启中…" : "↻ 重启"}
      </button>
      <button onClick={onOpenSettings} disabled={isOrphan} className="action-btn">
        ⚙ 设置
      </button>
      <button
        onClick={cycleExpandMode}
        className={expandMode === "smart" ? "action-btn" : "action-btn engaged"}
        title={expandTitle}
      >
        {expandLabel}
      </button>
    </div>
  );
}
