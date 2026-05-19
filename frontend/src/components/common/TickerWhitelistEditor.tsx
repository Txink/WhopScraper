import { useState } from "react";
import type { TickerConfig } from "../../api/domain-types";

interface Props {
  tickers: Record<string, TickerConfig>;
  onChange(next: Record<string, TickerConfig>): void;
  disabled?: boolean;
  /** API-level error from the host component (e.g. network failure). */
  error?: string | null;
}

/**
 * Pure-UI ticker whitelist chip editor.
 *
 * Renders a list of chips (``SYMBOL · QTY``, click to remove) plus an
 * inline add-form (ticker input + qty input + confirm/cancel buttons).
 *
 * No API calls. Validates locally (non-empty, positive integer, no
 * duplicate). The host component supplies `onChange` which is only called
 * with a validated, updated map. API-level errors are surfaced via the
 * `error` prop.
 *
 * Designed to be embedded inside either `PageWhitelistBar` (Dashboard) or
 * the chat-page settings modal.
 */
export function TickerWhitelistEditor({ tickers, onChange, disabled, error: apiError }: Props) {
  const [adding, setAdding] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [newQty, setNewQty] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const handleDelete = (ticker: string) => {
    if (disabled) return;
    const next = { ...tickers };
    delete next[ticker];
    onChange(next);
  };

  const handleStartAdd = () => {
    setAdding(true);
    setNewTicker("");
    setNewQty("");
    setFormError(null);
  };

  const handleCancelAdd = () => {
    setAdding(false);
    setNewTicker("");
    setNewQty("");
    setFormError(null);
  };

  const handleConfirmAdd = () => {
    const ticker = newTicker.trim().toUpperCase();
    const qty = Number(newQty);
    if (!ticker) {
      setFormError("ticker 不能为空");
      return;
    }
    if (!Number.isFinite(qty) || qty <= 0 || !Number.isInteger(qty)) {
      setFormError("数量必须是 > 0 的整数");
      return;
    }
    if (tickers[ticker]) {
      setFormError(`${ticker} 已存在`);
      return;
    }
    onChange({ ...tickers, [ticker]: { trade_quantity: qty } });
    // Keep the form open for rapid multi-add; just clear the draft fields.
    setNewTicker("");
    setNewQty("");
    setFormError(null);
  };

  const sortedTickers = Object.entries(tickers).sort(([a], [b]) => a.localeCompare(b));
  const displayError = formError ?? apiError;
  const tickerCount = sortedTickers.length;

  return (
    <>
      {!adding && tickerCount === 0 && (
        <span className="whitelist-empty">未配置 — 点 + 添加</span>
      )}

      {sortedTickers.map(([ticker, cfg]) => (
        <button
          key={ticker}
          type="button"
          className="ticker-chip"
          disabled={disabled}
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
          onSubmit={(e) => { e.preventDefault(); handleConfirmAdd(); }}
        >
          <input
            type="text"
            className="ticker-add-input ticker-name-input"
            placeholder="ticker"
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value)}
            autoFocus
            disabled={disabled}
            maxLength={8}
          />
          <span className="ticker-sep" aria-hidden="true">·</span>
          <input
            type="number"
            className="ticker-add-input ticker-qty-input"
            placeholder="qty"
            value={newQty}
            onChange={(e) => setNewQty(e.target.value)}
            disabled={disabled}
          />
          <button type="submit" className="ticker-add-confirm" disabled={disabled} aria-label="确认添加">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="2.5 6 5 8.5 9.5 3.5" />
            </svg>
          </button>
          <button
            type="button"
            className="ticker-add-cancel"
            disabled={disabled}
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
          disabled={disabled}
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

      {displayError && <span className="whitelist-error" role="alert">{displayError}</span>}
    </>
  );
}
