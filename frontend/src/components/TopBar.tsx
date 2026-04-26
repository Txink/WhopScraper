import { useState } from "react";
import "./TopBar.css";
import { useViewStore } from "../stores/view";

export interface TopBarProps {
  connLongport: "up" | "down" | "unknown";
  /** True iff backend's broker is a live LongPortClient. False = NoopClient
   *  fallback (init failed). Null/undefined = haven't fetched broker status. */
  brokerIsReal?: boolean | null;
  brokerInitError?: string | null;
  mode: "paper" | "real";
  dryRun: boolean;
  autoTrade?: boolean;
  onOpenLongportSettings?: () => void;
  /** Trigger a backend broker rebuild (POST /api/longport/broker/reload).
   *  When provided, the longport pill becomes clickable: hovering swaps
   *  the status content for a "⟳ 刷新" affordance, clicking runs the
   *  callback. The pill shows a spinning icon while the request is in
   *  flight; the resulting status flows back via the conn store. */
  onReloadBroker?: () => Promise<void> | void;
  onLogout?: () => void;
}

export function TopBar({
  connLongport,
  brokerIsReal = null,
  brokerInitError = null,
  mode,
  dryRun,
  autoTrade = false,
  onOpenLongportSettings,
  onReloadBroker,
  onLogout,
}: TopBarProps) {
  const view = useViewStore((s) => s.view);
  const setView = useViewStore((s) => s.setView);
  const [reloading, setReloading] = useState(false);

  const pillParts = [mode === "paper" ? "PAPER" : "REAL", dryRun ? "DRY" : "LIVE"];
  if (autoTrade) pillParts.push("AUTO");
  const pillLabel = pillParts.join(" · ");

  const handleLongportClick = async () => {
    if (!onReloadBroker || reloading) return;
    setReloading(true);
    try {
      await onReloadBroker();
    } finally {
      setReloading(false);
    }
  };

  const longportTitle =
    reloading
      ? "刷新中…"
      : brokerIsReal === null
        ? "broker 状态加载中 — 点击刷新"
        : brokerIsReal
          ? "broker 已连接 LongPort — 点击刷新"
          : `broker 未初始化（NoopClient）${brokerInitError ? "：" + brokerInitError : ""} — 点击刷新`;

  return (
    <header className="topbar">
      {/* Brand mark */}
      <div className="brand-mark">
        <span className="brand-dot" />
        <span className="brand-name">Signal Station</span>
      </div>

      {/* View switcher */}
      <nav className="topbar-views">
        <button
          className={view === "database" ? "view-btn active" : "view-btn"}
          onClick={() => setView("database")}
        >
          数据库
        </button>
        <button
          className={view === "dashboard" ? "view-btn active" : "view-btn"}
          onClick={() => setView("dashboard")}
        >
          监控看板
        </button>
        <button
          className={view === "whop" ? "view-btn active" : "view-btn"}
          onClick={() => setView("whop")}
        >
          Whop 管理
        </button>
      </nav>

      {/* Right cluster: conn indicators + account pill */}
      <div className="topbar-right">
        <div className="conn-group">
          <button
            type="button"
            className={`conn longport-conn ${reloading ? "reloading" : ""}`}
            data-broker-real={brokerIsReal === null ? "unknown" : brokerIsReal ? "true" : "false"}
            title={longportTitle}
            aria-label={reloading ? "刷新中" : "刷新 broker"}
            disabled={reloading || !onReloadBroker}
            onClick={handleLongportClick}
          >
            <span className={`conn-dot ${connLongport}`} />
            <span className="conn-label">longport</span>
            <span className="longport-refresh-icon" aria-hidden="true">
              <svg
                viewBox="0 0 14 14"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={reloading ? "spinning" : ""}
              >
                <path d="M2 7a5 5 0 0 1 9-3" />
                <polyline points="11.5 1.5 11.5 4 9 4" />
                <path d="M12 7a5 5 0 0 1-9 3" />
                <polyline points="2.5 12.5 2.5 10 5 10" />
              </svg>
            </span>
          </button>
        </div>
        <button
          type="button"
          className={`acct-pill ${mode}`}
          onClick={onOpenLongportSettings}
          title="LongPort 设置"
        >
          {pillLabel}
        </button>
        {onLogout && (
          <button
            className="logout-btn"
            onClick={onLogout}
            title="退出登录"
            aria-label="退出登录"
          >
            ⎋
          </button>
        )}
      </div>
    </header>
  );
}
