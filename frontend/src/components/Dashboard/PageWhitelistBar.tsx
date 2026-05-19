import { useState } from "react";
import type { WhopPage, WhopPageSettingsPatch } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { TickerWhitelistEditor } from "../common/TickerWhitelistEditor";

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
 * Thin wrapper around `TickerWhitelistEditor` that handles persistence via
 * `api.updateWhopPageSettings`. State changes are broadcast through the WS
 * `page.settings_updated` event which refreshes `page` in the global
 * pageTabs store.
 */
export function PageWhitelistBar({ page }: Props) {
  const tickers = page.settings.tickers ?? {};

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleChange = async (next: Record<string, { trade_quantity: number }>) => {
    setBusy(true);
    setError(null);
    try {
      await api.updateWhopPageSettings(page.id, { tickers: next } as WhopPageSettingsPatch);
    } catch (e) {
      setError(_toMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page-whitelist-bar">
      <span className="whitelist-label">白名单</span>

      <TickerWhitelistEditor
        tickers={tickers}
        onChange={(next) => void handleChange(next)}
        disabled={busy}
        error={error}
      />
    </div>
  );
}
