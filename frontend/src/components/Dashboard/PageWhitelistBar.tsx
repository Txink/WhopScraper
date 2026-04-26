import { useState } from "react";
import type { WhopPage, WhopPageSettings } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";

interface Props {
  page: WhopPage;
}

function _toMessage(e: unknown): string {
  if (e instanceof HttpError) {
    if (typeof e.body === "object" && e.body && "detail" in e.body) {
      return String((e.body as { detail: unknown }).detail);
    }
    return e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

/**
 * Inline whitelist editor — sits below the page header on stock pages.
 *
 * Each ticker renders as a chip ``TICKER · QTY``. Hovering switches the
 * chip to a "delete" affordance (red tint + ✕ glyph); clicking the chip
 * removes the ticker. A trailing ``+`` button reveals an inline form to
 * add a new ticker without opening the settings modal.
 *
 * Persists by calling ``api.updateWhopPageSettings`` with a fresh
 * ``tickers`` map; the WS ``page.settings_updated`` event then refreshes
 * ``page`` in the global pageTabs store.
 */
export function PageWhitelistBar({ page }: Props) {
  const tickers = page.settings.tickers ?? {};
  const sortedTickers = Object.entries(tickers).sort(([a], [b]) => a.localeCompare(b));

  const [adding, setAdding] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [newQty, setNewQty] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const persist = async (next: Record<string, { trade_quantity: number }>) => {
    setBusy(true);
    setError(null);
    try {
      await api.updateWhopPageSettings(page.id, { tickers: next } as Partial<WhopPageSettings> as WhopPageSettings);
    } catch (e) {
      setError(_toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (ticker: string) => {
    if (busy) return;
    const next = { ...tickers };
    delete next[ticker];
    await persist(next);
  };

  const handleStartAdd = () => {
    setAdding(true);
    setNewTicker("");
    setNewQty("");
    setError(null);
  };

  const handleCancelAdd = () => {
    setAdding(false);
    setError(null);
  };

  const handleConfirmAdd = async () => {
    const ticker = newTicker.trim().toUpperCase();
    const qty = Number(newQty);
    if (!ticker) {
      setError("ticker 不能为空");
      return;
    }
    if (!Number.isFinite(qty) || qty <= 0 || !Number.isInteger(qty)) {
      setError("数量必须是 > 0 的整数");
      return;
    }
    if (tickers[ticker]) {
      setError(`${ticker} 已存在`);
      return;
    }
    const next = { ...tickers, [ticker]: { trade_quantity: qty } };
    await persist(next);
    if (!error) {
      setAdding(false);
      setNewTicker("");
      setNewQty("");
    }
  };

  return (
    <div className="page-whitelist-bar">
      <span className="whitelist-label">白名单</span>

      {sortedTickers.length === 0 && !adding && (
        <span className="whitelist-empty">未配置 — 点 + 添加</span>
      )}

      {sortedTickers.map(([ticker, cfg]) => (
        <button
          key={ticker}
          type="button"
          className="ticker-chip"
          disabled={busy}
          onClick={() => handleDelete(ticker)}
          aria-label={`删除 ${ticker}`}
          title={`点击删除 ${ticker}`}
        >
          <span className="ticker-name">{ticker}.US</span>
          <span className="ticker-sep" aria-hidden="true">·</span>
          <span className="ticker-qty">{cfg.trade_quantity}</span>
          <span className="ticker-del-icon" aria-hidden="true">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
              <line x1="3" y1="3" x2="9" y2="9" />
              <line x1="9" y1="3" x2="3" y2="9" />
            </svg>
          </span>
        </button>
      ))}

      {adding ? (
        <form
          className="ticker-add-form"
          onSubmit={(e) => { e.preventDefault(); void handleConfirmAdd(); }}
        >
          <input
            type="text"
            className="ticker-add-input ticker-name-input"
            placeholder="ticker"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            autoFocus
            disabled={busy}
            maxLength={8}
          />
          <span className="ticker-sep" aria-hidden="true">·</span>
          <input
            type="number"
            className="ticker-add-input ticker-qty-input"
            placeholder="qty"
            value={newQty}
            onChange={(e) => setNewQty(e.target.value)}
            disabled={busy}
          />
          <button type="submit" className="ticker-add-confirm" disabled={busy} aria-label="确认添加">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="2.5 6 5 8.5 9.5 3.5" />
            </svg>
          </button>
          <button
            type="button"
            className="ticker-add-cancel"
            disabled={busy}
            onClick={handleCancelAdd}
            aria-label="取消"
          >
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="3" x2="9" y2="9" />
              <line x1="9" y1="3" x2="3" y2="9" />
            </svg>
          </button>
        </form>
      ) : (
        <button
          type="button"
          className="ticker-add-btn"
          disabled={busy}
          onClick={handleStartAdd}
          aria-label="添加 ticker"
          title="添加 ticker"
        >
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <line x1="6" y1="2.5" x2="6" y2="9.5" />
            <line x1="2.5" y1="6" x2="9.5" y2="6" />
          </svg>
        </button>
      )}

      {error && <span className="whitelist-error" role="alert">{error}</span>}
    </div>
  );
}
