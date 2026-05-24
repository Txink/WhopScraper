import type { OrderOut } from "../../../api/orders";

interface Props {
  orders: OrderOut[];
  activeOnly?: boolean;
  onReplace: (order: OrderOut) => void;
  onCancel: (order: OrderOut) => void;
}

const TERMINAL = new Set(["FilledStatus", "CancelledStatus", "RejectedStatus", "Filled", "Cancelled", "Rejected"]);

function isTerminal(o: OrderOut): boolean {
  return TERMINAL.has(o.status) || (o.filled_qty >= o.qty && o.qty > 0);
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function ActiveOrdersTable({ orders, activeOnly, onReplace, onCancel }: Props) {
  const visible = activeOnly ? orders.filter((o) => !isTerminal(o)) : orders;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>时间</th><th>代码</th><th>方向</th><th>类型</th>
          <th className="num">价格</th><th className="num">数量</th>
          <th className="num">已成</th><th>状态</th><th>来源</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((o) => {
          const done = isTerminal(o);
          const sideClass = o.side === "BUY" ? "buy" : "sell";
          return (
            <tr key={o.order_id}>
              <td>{fmtTime(o.submitted_at)}</td>
              <td>{o.ticker}</td>
              <td><span className={`side-pill ${sideClass}`}>{o.side}</span></td>
              <td>{o.order_type === "LIMIT" ? "LIMIT" : "MKT"}</td>
              <td className="num">{o.price != null ? `$${o.price.toFixed(3)}` : "—"}</td>
              <td className="num">{o.qty}</td>
              <td className="num">{o.filled_qty}</td>
              <td>{o.status}</td>
              <td><span style={{ fontSize: 10, color: "var(--fg-3)" }}>
                {o.source === "manual" ? "手动" : o.source === "signal" ? "信号" : "长桥app"}
              </span></td>
              <td>
                <div className="row-actions">
                  <button className="row-btn" disabled={done} onClick={() => onReplace(o)}>改</button>
                  <button className="row-btn danger" disabled={done} onClick={() => onCancel(o)}>撤</button>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
