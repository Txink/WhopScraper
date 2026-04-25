import { useRef, useState } from "react";
import type { WhopPage, WhopPageSettings } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import "./PageSettingsModal.css";

interface Props {
  page: WhopPage;
  onClose: () => void;
}

interface TickerRow {
  rowId: string;
  ticker: string;
  trade_quantity: number;
}

export function PageSettingsModal({ page, onClose }: Props) {
  const [dedupe, setDedupe] = useState(page.settings.dedupe_processed_messages);
  const [tolerance, setTolerance] = useState(String(page.settings.price_deviation_tolerance));

  const initialTickers = page.settings.tickers ?? {};
  const nextRowId = useRef(Object.keys(initialTickers).length);
  const newRowId = () => `row-${++nextRowId.current}`;

  const [tickerRows, setTickerRows] = useState<TickerRow[]>(() =>
    Object.entries(initialTickers).map(([ticker, cfg], i) => ({
      rowId: `row-${i}`,
      ticker,
      trade_quantity: cfg.trade_quantity,
    }))
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const initialDedupe = page.settings.dedupe_processed_messages;
  const dedupeChanged = dedupe !== initialDedupe;

  const handleAddTicker = () => {
    setTickerRows(prev => [...prev, { rowId: newRowId(), ticker: "", trade_quantity: 0 }]);
  };
  const handleRemoveTicker = (rowId: string) => {
    setTickerRows(prev => prev.filter(r => r.rowId !== rowId));
  };
  const handleEditTickerName = (rowId: string, name: string) => {
    setTickerRows(prev => prev.map(r => (r.rowId === rowId ? { ...r, ticker: name } : r)));
  };
  const handleEditTickerQty = (rowId: string, qty: number) => {
    setTickerRows(prev => prev.map(r => (r.rowId === rowId ? { ...r, trade_quantity: qty } : r)));
  };

  const handleSave = async () => {
    setError(null);
    const tolNum = Number(tolerance);
    if (Number.isNaN(tolNum) || tolNum < 0) {
      setError("价格偏差必须 ≥ 0");
      return;
    }
    if (page.source === "stock") {
      for (const r of tickerRows) {
        if (!r.ticker.trim()) { setError("ticker 不能为空"); return; }
        if (!Number.isFinite(r.trade_quantity) || r.trade_quantity <= 0) {
          setError(`${r.ticker}: 数量必须 > 0`);
          return;
        }
      }
    }
    setSaving(true);
    try {
      const patch: Partial<WhopPageSettings> = {
        dedupe_processed_messages: dedupe,
        price_deviation_tolerance: tolNum,
      };
      if (page.source === "stock") {
        patch.tickers = Object.fromEntries(
          tickerRows.map(r => [r.ticker.toUpperCase(), { trade_quantity: r.trade_quantity }])
        );
      }
      await api.updateWhopPageSettings(page.id, patch as WhopPageSettings);
      onClose();
    } catch (e) {
      if (e instanceof HttpError) {
        setError(typeof e.body === "object" && e.body && "detail" in e.body
          ? String((e.body as { detail: unknown }).detail)
          : e.message);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <header>
          <h3>{page.name} · 设置</h3>
          <button className="close" onClick={onClose} aria-label="关闭">✕</button>
        </header>

        <div className="modal-body">
          <section>
            <label>
              <input type="checkbox" checked={dedupe} onChange={e => setDedupe(e.target.checked)} />
              <span>避免重复解析消息（启动 / 重启时跳过 DB 中已存在的 domID）</span>
            </label>
            {dedupeChanged && (
              <p className="hint warn">△ 下次重启监听才生效（点上面操作行的"重启"按钮）</p>
            )}
          </section>

          <section>
            <label htmlFor="tol">价格偏差容忍（%）</label>
            <input
              id="tol" type="number" step="0.1" min="0"
              value={tolerance}
              onChange={e => setTolerance(e.target.value)}
            />
            <p className="hint small">
              市价偏离信号价 ≤ 此值 → 直接市价单；&gt; 此值 → 限价单 @ 信号价
            </p>
          </section>

          {page.source === "stock" && (
            <section>
              <h4>股票配置</h4>
              <p className="hint small">
                只有列表里的 ticker 才会触发下单；trade_quantity 是"常规仓"的整股数（半仓 ÷2、1/3 仓 ÷3）。
              </p>
              <table className="tickers-table">
                <thead><tr><th>Ticker</th><th>常规仓数量</th><th /></tr></thead>
                <tbody>
                  {tickerRows.map(row => (
                    <tr key={row.rowId}>
                      <td>
                        <input
                          className="ticker-input"
                          placeholder="输入 ticker"
                          value={row.ticker}
                          onChange={e => handleEditTickerName(row.rowId, e.target.value)}
                        />
                      </td>
                      <td>
                        <input
                          type="number" min="1" placeholder="数量"
                          value={row.trade_quantity || ""}
                          onChange={e => handleEditTickerQty(row.rowId, Number(e.target.value))}
                        />
                      </td>
                      <td>
                        <button onClick={() => handleRemoveTicker(row.rowId)} className="del" aria-label="删除">✕</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button onClick={handleAddTicker} className="add-link">+ 添加 ticker</button>
            </section>
          )}

          {error && <div className="error">{error}</div>}
        </div>

        <footer>
          <button onClick={onClose}>取消</button>
          <button onClick={handleSave} disabled={saving} className="primary">
            {saving ? "保存中…" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
