import { useState } from "react";
import { api } from "../../api/http";
import { usePageTabsStore } from "../../stores/pageTabs";
import type { ExpandMode } from "../../stores/pageTabs";
import type { WhopPage } from "../../api/domain-types";
import {
  CollapseAllIcon,
  ExpandAllIcon,
  PowerIcon,
  SettingsIcon,
  SmartIcon,
} from "./icons";

interface Props {
  page: WhopPage | null;
  mode: "page" | "orphan";
  onOpenSettings: () => void;
}

export function PageActionBar({ page, mode, onOpenSettings }: Props) {
  const [busy, setBusy] = useState(false);
  const isReadonlyTab = mode !== "page" || page === null;
  const tabId = mode === "orphan" ? "orphan" : (page?.id ?? "orphan");
  const expandMode = usePageTabsStore(s => s.expandModeByTab[tabId] ?? "smart");
  const setExpand = usePageTabsStore(s => s.setExpandMode);

  // Power toggle: stop if running, start otherwise. The backend start endpoint
  // is restart-style (stop existing + fresh start with skip_initial=False), so
  // it's safe to call even on a "stuck" listener.
  const handleToggle = async () => {
    if (isReadonlyTab || !page) return;
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

  // Tri-state expand toggle — icon-only. Each state shows a different
  // glyph + tooltip + aria-label so the meaning is clear without a text
  // label, and tests can locate the button by its current aria-label.
  const expandTitle =
    expandMode === "smart" ? "智能展开 — 点击切换为全部展开"
    : expandMode === "all-open" ? "全部展开 — 点击切换为全部收起"
    : "全部收起 — 点击回到智能模式";

  const expandAria =
    expandMode === "smart" ? "智能展开"
    : expandMode === "all-open" ? "全部展开"
    : "全部收起";

  const expandIcon =
    expandMode === "smart" ? <SmartIcon size={16} />
    : expandMode === "all-open" ? <ExpandAllIcon size={16} />
    : <CollapseAllIcon size={16} />;

  return (
    <div className="page-action-bar">
      <button
        onClick={handleToggle}
        disabled={isReadonlyTab || busy}
        className={powerClass}
        title={powerTitle}
        aria-label={powerAria}
      >
        <PowerIcon size={18} />
      </button>
      <button
        onClick={onOpenSettings}
        disabled={isReadonlyTab}
        className="action-btn icon-only"
        title="设置"
        aria-label="设置"
      >
        <SettingsIcon size={22} />
      </button>
      <button
        onClick={cycleExpandMode}
        className={
          "action-btn icon-only "
          + (expandMode === "smart" ? "" : "engaged ")
          + `expand-mode-${expandMode}`
        }
        title={expandTitle}
        aria-label={expandAria}
      >
        {expandIcon}
      </button>
    </div>
  );
}
