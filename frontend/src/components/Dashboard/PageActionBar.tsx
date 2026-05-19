import { useState } from "react";
import { api } from "../../api/http";
import type { WhopPage } from "../../api/domain-types";
import {
  ExportIcon,
  PowerIcon,
  SettingsIcon,
} from "./icons";

interface Props {
  page: WhopPage | null;
  mode: "page" | "orphan";
  onOpenSettings: () => void;
  /** Optional export action — chat pages pass an exporter; others omit
   *  it and the export button isn't rendered. */
  onExport?: () => void;
}

export function PageActionBar({ page, mode, onOpenSettings, onExport }: Props) {
  const [busy, setBusy] = useState(false);
  const isReadonlyTab = mode !== "page" || page === null;

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

  // Tri-state visual: off / on / err. last_error takes precedence over running so
  // a listener stuck in its error-backoff loop shows red immediately — the backend
  // publishes errored/recovered events on transitions (see app/whop/listener.py).
  let powerClass = "power-btn icon-only off";
  let powerTitle = "开机 — 启动监听";
  let powerAria = "开机";
  if (page) {
    if (page.last_error) {
      powerClass = "power-btn icon-only err";
      powerTitle = `错误：${page.last_error}`;
      // aria reflects the action click will perform — depends on running, since
      // handleToggle still dispatches by page.running.
      powerAria = page.running ? "错误，点击关机" : "错误，点击重试";
    } else if (page.running) {
      powerClass = "power-btn icon-only on";
      powerTitle = "运行中 — 点击关机";
      powerAria = "关机";
    }
  }

  // Expand mode is no longer user-toggleable — the card list is a fixed
  // single-card accordion (default everything collapsed; click expands;
  // clicking another collapses the prior). The mode-cycle button used to
  // sit alongside power/settings; removing it shortens the action bar.

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
      {onExport && (
        <button
          onClick={onExport}
          disabled={isReadonlyTab}
          className="action-btn icon-only"
          title="导出 JSON"
          aria-label="导出 JSON"
        >
          <ExportIcon size={16} />
        </button>
      )}
      <button
        onClick={onOpenSettings}
        disabled={isReadonlyTab}
        className="action-btn icon-only"
        title="设置"
        aria-label="设置"
      >
        <SettingsIcon size={22} />
      </button>
    </div>
  );
}
