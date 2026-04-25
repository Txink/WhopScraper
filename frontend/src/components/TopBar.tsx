import "./TopBar.css";

export interface TopBarProps {
  connWhop: "up" | "down" | "unknown";
  connLongport: "up" | "down" | "unknown";
  mode: "paper" | "real";
  dryRun: boolean;
}

const FILTER_LABELS = ["全部", "正股", "期权", "已成交", "解析失败"] as const;

export function TopBar({ connWhop, connLongport, mode, dryRun }: TopBarProps) {
  const pillLabel = `${mode === "paper" ? "PAPER" : "REAL"} · ${dryRun ? "DRY" : "LIVE"}`;

  return (
    <header className="topbar">
      {/* Brand mark */}
      <div className="brand-mark">
        <span className="brand-dot" />
        <span className="brand-name">Signal Station</span>
        <span className="brand-sep" />
        <span className="brand-sub">whop → longport</span>
      </div>

      {/* Filter chips */}
      <nav className="filters">
        {FILTER_LABELS.map((label) => (
          <button
            key={label}
            className={`filter-chip${label === "全部" ? " active" : ""}`}
            onClick={() => {}}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Right cluster: conn indicators + account pill */}
      <div className="topbar-right">
        <div className="conn-group">
          <div className="conn">
            <span className={`conn-dot ${connWhop}`} />
            <span className="conn-label">whop</span>
          </div>
          <div className="conn">
            <span className={`conn-dot ${connLongport}`} />
            <span className="conn-label">longport</span>
          </div>
        </div>
        <span className={`acct-pill ${mode}`}>{pillLabel}</span>
      </div>
    </header>
  );
}
