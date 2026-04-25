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
  const [busy, setBusy] = useState(false);
  const isOrphan = page === null;
  const tabId = isOrphan ? "orphan" : page!.id;
  const expandMode = usePageTabsStore(s => s.expandModeByTab[tabId] ?? "smart");
  const setExpand = usePageTabsStore(s => s.setExpandMode);

  // Power toggle: stop if running, start otherwise. The backend start endpoint
  // is restart-style (stop existing + fresh start with skip_initial=False), so
  // it's safe to call even on a "stuck" listener.
  const handleToggle = async () => {
    if (isOrphan || !page) return;
    setBusy(true);
    try {
      if (page.running) {
        await api.stopWhopPage(page.id);
      } else {
        await api.startWhopPage(page.id);
      }
    } catch (e) {
      alert(`操作失败：${e instanceof Error ? e.message : e}`);
    } finally {
      setBusy(false);
    }
  };

  // Tri-state visual: off (gray) / on (green) / err (red, tooltip = last_error).
  // Note: running=true with a stale last_error is treated as "on" — the user
  // can still see the error by stopping and inspecting; we don't want a green
  // listener to show as red.
  let powerClass = "power-btn icon-only off";
  let powerTitle = "开机 — 启动监听";
  let powerAria = "开机";
  if (page) {
    if (page.running) {
      powerClass = "power-btn icon-only on";
      powerTitle = "运行中 — 点击关机";
      powerAria = "关机";
    } else if (page.last_error) {
      powerClass = "power-btn icon-only err";
      powerTitle = `错误：${page.last_error}`;
      powerAria = "错误，点击重试";
    }
  }

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
      <button
        onClick={handleToggle}
        disabled={isOrphan || busy}
        className={powerClass}
        title={powerTitle}
        aria-label={powerAria}
      >
        ⏻
      </button>
      <button
        onClick={onOpenSettings}
        disabled={isOrphan}
        className="action-btn icon-only"
        title="设置"
        aria-label="设置"
      >
        ⚙
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
