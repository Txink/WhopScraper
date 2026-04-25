import "./RightRail.css";

// Phase 8: all stubs. Phase 9 passes real data.
export interface RightRailProps {}

function RailCard({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="rail-card">
      <div className="rail-card-title">{title}</div>
      {children ?? <p className="rail-empty">暂无数据</p>}
    </div>
  );
}

export function RightRail(_props: RightRailProps) {
  return (
    <aside className="rail">
      <RailCard title="今日" />
      <RailCard title="正股持仓" />
      <RailCard title="期权持仓" />
    </aside>
  );
}
