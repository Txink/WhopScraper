import { useEffect, useMemo, useRef, useState } from "react";
import { isOrderActionable, isOrderTerminal, type OrderOut } from "../../../api/orders";

interface Props {
  orders: OrderOut[];
  activeOnly?: boolean;
  /** Fires when the user commits an inline edit (blur or Enter) to a
   *  price or quantity cell. Only the changed field is provided; the
   *  caller posts a broker replace_order with whichever field is set. */
  onReplace: (
    order: OrderOut,
    change: { price?: number | null; qty?: number | null },
  ) => void;
  onCancel: (order: OrderOut) => void;
}


function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** The LongPort SDK serialises order status as ``OrderStatus.Foo``;
 *  strip the enum prefix so the table reads ``Foo``. Anything else
 *  (e.g. our own "SUBMITTING") passes through unchanged. */
function fmtStatus(s: string): string {
  return s.startsWith("OrderStatus.") ? s.slice("OrderStatus.".length) : s;
}

/** Inline-editable numeric cell. Keeps local edit state, commits on
 *  blur or Enter when the value differs from the baseline, reverts on
 *  Escape or invalid input. When the underlying order updates (e.g.
 *  after a successful broker replace), the cell resyncs. */
function EditableNumCell({
  initial,
  decimals,
  disabled,
  ariaLabel,
  onCommit,
}: {
  initial: string;
  decimals: number;
  disabled: boolean;
  ariaLabel: string;
  onCommit: (next: number) => void;
}) {
  const [val, setVal] = useState(initial);
  const baseline = useRef(initial);
  // Set by the Escape handler before blur fires so onBlur knows to
  // skip the commit. React state updates are async, so checking `val`
  // inside onBlur would still see the pre-revert string.
  const revertingRef = useRef(false);

  useEffect(() => {
    setVal(initial);
    baseline.current = initial;
  }, [initial]);

  if (disabled) return <span>{initial}</span>;

  const commit = () => {
    if (revertingRef.current) {
      revertingRef.current = false;
      setVal(baseline.current);
      return;
    }
    if (val === baseline.current) return;
    const n = decimals === 0 ? parseInt(val, 10) : parseFloat(val);
    if (!Number.isFinite(n) || n <= 0) {
      setVal(baseline.current);
      return;
    }
    onCommit(n);
  };

  return (
    <input
      className={`tbl-edit${decimals === 0 ? " tbl-edit-int" : ""}`}
      aria-label={ariaLabel}
      value={val}
      onChange={(e) => setVal(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
        if (e.key === "Escape") {
          revertingRef.current = true;
          (e.currentTarget as HTMLInputElement).blur();
        }
      }}
    />
  );
}

export function ActiveOrdersTable({ orders, activeOnly, onReplace, onCancel }: Props) {
  // Dedupe by order_id (last write wins → keeps the freshest broker state
  // if the upstream list ever leaks duplicates) and sort newest-first so
  // the row order matches the natural reading expectation. Defensive: the
  // backend already merges by order_id in OrdersService.list_today, but
  // the store's setOrders/upsertOrder don't guarantee uniqueness if the
  // backend ever regresses or WS pushes interleave with a fresh refetch.
  const visible = useMemo(() => {
    const filtered = activeOnly ? orders.filter((o) => !isOrderTerminal(o)) : orders;
    const byId = new Map<string, OrderOut>();
    for (const o of filtered) byId.set(o.order_id, o);
    return [...byId.values()].sort((a, b) => {
      const ta = a.submitted_at ? new Date(a.submitted_at).getTime() : 0;
      const tb = b.submitted_at ? new Date(b.submitted_at).getTime() : 0;
      return tb - ta;
    });
  }, [orders, activeOnly]);
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>时间</th><th>方向</th><th>类型</th>
          <th className="num">价格</th><th className="num">数量</th>
          <th className="num">已成</th><th>状态</th><th>来源</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((o) => {
          // Disable per-row inputs/buttons for both terminal orders AND
          // orders with a cancel already racing through the broker.
          const locked = !isOrderActionable(o);
          const sideClass = o.side === "BUY" ? "buy" : "sell";
          const priceEditable = o.order_type === "LIMIT" && o.price != null;
          return (
            <tr key={o.order_id}>
              <td>{fmtTime(o.submitted_at)}</td>
              <td><span className={`side-pill ${sideClass}`}>{o.side}</span></td>
              <td>{o.order_type === "LIMIT" ? "LIMIT" : "MKT"}</td>
              <td className="num">
                {priceEditable ? (
                  <EditableNumCell
                    initial={o.price!.toFixed(3)}
                    decimals={3}
                    disabled={locked}
                    ariaLabel={`价格 ${o.ticker}`}
                    onCommit={(np) => onReplace(o, { price: np })}
                  />
                ) : (
                  <span>{o.price != null ? `$${o.price.toFixed(3)}` : "—"}</span>
                )}
              </td>
              <td className="num">
                <EditableNumCell
                  initial={String(o.qty)}
                  decimals={0}
                  disabled={locked}
                  ariaLabel={`数量 ${o.ticker}`}
                  onCommit={(nq) => onReplace(o, { qty: nq })}
                />
              </td>
              <td className="num">{o.filled_qty}</td>
              <td>{fmtStatus(o.status)}</td>
              <td><span style={{ fontSize: 10, color: "var(--fg-3)" }}>
                {o.source === "manual" ? "手动" : o.source === "signal" ? "信号" : "长桥app"}
              </span></td>
              <td>
                <div className="row-actions">
                  <button className="row-btn danger" disabled={locked} onClick={() => onCancel(o)}>撤</button>
                </div>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
