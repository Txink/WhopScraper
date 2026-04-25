import { useStatsStore } from "../stores/stats";
import { usePositionsStore } from "../stores/positions";
import "./RightRail.css";

export function RightRail() {
  const stats = useStatsStore((s) => s.stats);
  const stocks = usePositionsStore((s) => s.stocks);
  const options = usePositionsStore((s) => s.options);

  return (
    <aside className="rail">
      {/* 今日 */}
      <div className="rail-card">
        <h3>今日</h3>
        {stats ? (
          <>
            <MetricRow label="消息" value={String(stats.msg_count)} />
            <MetricRow
              label="解析成功"
              value={
                <>
                  {stats.parse_ok}
                  <span className="sub">{(stats.parse_rate * 100).toFixed(1)}%</span>
                </>
              }
              tone="pos"
            />
            <MetricRow label="已下单" value={String(stats.orders)} />
            <MetricRow label="已成交" value={String(stats.filled)} tone="pos" />
            <MetricRow
              label="被拒/超差"
              value={String(stats.rejected)}
              tone={stats.rejected > 0 ? "neg" : undefined}
            />
          </>
        ) : (
          <EmptyRow />
        )}
      </div>

      {/* 正股持仓 */}
      <div className="rail-card">
        <h3>
          正股持仓 <span className="count">{stocks.length}</span>
        </h3>
        {stocks.length > 0 ? (
          stocks.map((p) => (
            <MetricRow
              key={p.symbol}
              label={
                <>
                  {p.symbol}
                  {p.avg_cost != null && <small>@ {p.avg_cost.toFixed(2)}</small>}
                </>
              }
              value={p.quantity.toLocaleString()}
            />
          ))
        ) : (
          <EmptyRow />
        )}
      </div>

      {/* 期权持仓 */}
      <div className="rail-card">
        <h3>
          期权持仓 <span className="count">{options.length}</span>
        </h3>
        {options.length > 0 ? (
          options.map((p) => (
            <MetricRow
              key={p.symbol}
              label={
                <>
                  {p.ticker} {p.option_strike}
                  {p.option_type === "CALL" ? "C" : p.option_type === "PUT" ? "P" : ""}
                  {p.option_expiry && <small>· {p.option_expiry.replace(/-/g, "")}</small>}
                </>
              }
              value={p.quantity.toLocaleString()}
            />
          ))
        ) : (
          <EmptyRow />
        )}
      </div>
    </aside>
  );
}

interface MetricRowProps {
  label: React.ReactNode;
  value: React.ReactNode;
  tone?: "pos" | "neg";
}

function MetricRow({ label, value, tone }: MetricRowProps) {
  const toneClass = tone ? ` ${tone}` : "";
  return (
    <div className="metric-row">
      <span className="metric-label">{label}</span>
      <span className={`metric-val${toneClass}`}>{value}</span>
    </div>
  );
}

function EmptyRow() {
  return <div className="rail-empty">暂无数据</div>;
}
