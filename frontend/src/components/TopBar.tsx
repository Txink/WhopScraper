import "./TopBar.css";
import { useViewStore } from "../stores/view";

export interface TopBarProps {
  connLongport: "up" | "down" | "unknown";
  mode: "paper" | "real";
  dryRun: boolean;
  autoTrade?: boolean;
  onOpenLongportSettings?: () => void;
  onLogout?: () => void;
}

export function TopBar({
  connLongport,
  mode,
  dryRun,
  autoTrade = false,
  onOpenLongportSettings,
  onLogout,
}: TopBarProps) {
  const view = useViewStore((s) => s.view);
  const setView = useViewStore((s) => s.setView);

  const pillParts = [mode === "paper" ? "PAPER" : "REAL", dryRun ? "DRY" : "LIVE"];
  if (autoTrade) pillParts.push("AUTO");
  const pillLabel = pillParts.join(" · ");

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
          <div className="conn">
            <span className={`conn-dot ${connLongport}`} />
            <span className="conn-label">longport</span>
          </div>
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
