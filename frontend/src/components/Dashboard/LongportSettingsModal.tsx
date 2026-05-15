import { useEffect, useRef, useState } from "react";
import { api, HttpError } from "../../api/http";
import type { LongportSettings, LongportAccount } from "../../api/domain-types";
import { usePrefsStore } from "../../stores/prefs";
import { usePositionsStore } from "../../stores/positions";
import { useQuotesStore } from "../../stores/quotes";
import { useCandlesticksStore } from "../../stores/candlesticks";
import { usePairsStore } from "../../stores/pairs";
import { useTradesStore } from "../../stores/trades";
import { useExecutionsStore } from "../../stores/executions";
import "./LongportSettingsModal.css";

interface Props {
  onClose: () => void;
  onSaved: (settings: LongportSettings) => void;
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

type SlotLabel = "paper" | "real";

interface OAuthFlight {
  slot: SlotLabel;
  sessionId: string;
  authUrl: string;
  accountId: string;
  startedAt: number;
}

const OAUTH_POLL_INTERVAL_MS = 2000;
const OAUTH_FLIGHT_TIMEOUT_MS = 5 * 60 * 1000;
const REGION_PATCH_DEBOUNCE_MS = 400;

function clearAccountCaches(): void {
  usePositionsStore.getState().reset();
  useQuotesStore.setState({ quotesBySymbol: {} });
  useCandlesticksStore.setState({ byKey: {} });
  usePairsStore.setState({ byTicker: {} });
  useTradesStore.setState({ byTicker: {} });
  useExecutionsStore.setState({ executions: [] });
}

async function reloadPositions(): Promise<void> {
  try {
    const positions = await api.positions();
    usePositionsStore.getState().setAll(positions);
  } catch (e) {
    console.warn("positions reload failed:", e);
  }
}

/** Find the account bound to a given slot label (paper / real), if any.
 *  The multi-account backend stores accounts by client_id; we map to slot
 *  semantics by matching on the user-visible ``label`` field. */
function slotAccount(
  accounts: LongportAccount[],
  slot: SlotLabel,
): LongportAccount | null {
  return accounts.find((a) => a.label === slot) ?? null;
}

export function LongportSettingsModal({ onClose, onSaved }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<LongportSettings | null>(null);

  const [flight, setFlight] = useState<OAuthFlight | null>(null);
  const [busySlot, setBusySlot] = useState<SlotLabel | null>(null);
  const [reloadingSlot, setReloadingSlot] = useState<SlotLabel | null>(null);
  const pollTimer = useRef<number | null>(null);
  const regionTimer = useRef<number | null>(null);

  const colorMode = usePrefsStore((s) => s.colorMode);
  const setColorMode = usePrefsStore((s) => s.setColorMode);

  const refreshSettings = async (): Promise<LongportSettings | null> => {
    try {
      const fresh = await api.getLongportSettings();
      setForm(fresh);
      return fresh;
    } catch (e) {
      setError(_toMessage(e));
      return null;
    }
  };

  const applyChange = async (patch: Partial<LongportSettings>) => {
    if (!form) return;
    const prev = form;
    const optimistic = { ...form, ...patch };
    setForm(optimistic);
    setError(null);
    try {
      const saved = await api.updateLongportSettings({
        auto_trade: optimistic.auto_trade,
        region: optimistic.region,
        dry_run: optimistic.dry_run,
      });
      setForm(saved);
      onSaved(saved);
    } catch (e) {
      setError(_toMessage(e));
      setForm(prev);
    }
  };

  /** Activate the account bound to ``slot``, then reload broker + refresh
   *  positions. No-op if the slot has no account or is already active. */
  const activateSlot = async (slot: SlotLabel) => {
    if (!form) return;
    const acct = slotAccount(form.accounts, slot);
    if (!acct) return;
    if (form.active_account_id === acct.account_id) return;
    const prev = form;
    setReloadingSlot(slot);
    setError(null);
    try {
      const saved = await api.activateLongportAccount(acct.account_id);
      setForm(saved);
      onSaved(saved);
      clearAccountCaches();
      await api.reloadBroker();
      await reloadPositions();
    } catch (e) {
      setError(_toMessage(e));
      setForm(prev);
    } finally {
      setReloadingSlot(null);
    }
  };

  useEffect(() => {
    let alive = true;
    api
      .getLongportSettings()
      .then((settings) => {
        if (alive) setForm(settings);
      })
      .catch((e: unknown) => {
        if (alive) setError(_toMessage(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
      if (regionTimer.current !== null) window.clearTimeout(regionTimer.current);
    };
  }, []);

  const cancelFlight = () => {
    if (pollTimer.current !== null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
    setFlight(null);
  };

  const pollOnce = async (f: OAuthFlight) => {
    if (Date.now() - f.startedAt > OAUTH_FLIGHT_TIMEOUT_MS) {
      setError("OAuth 授权超时，请重试。");
      cancelFlight();
      return;
    }
    try {
      const status = await api.longportOauthStatus(f.sessionId);
      if (status.state === "success") {
        // Rename the new account to the slot label (paper / real) before
        // anything else looks at the list, so the slot binding is stable.
        try {
          await api.renameLongportAccount(f.accountId, f.slot);
        } catch (e) {
          console.warn("rename after oauth failed:", e);
        }
        const fresh = await refreshSettings();
        if (fresh) {
          setReloadingSlot(f.slot);
          try {
            if (fresh.active_account_id !== f.accountId) {
              const updated = await api.activateLongportAccount(f.accountId);
              setForm(updated);
              onSaved(updated);
            } else {
              onSaved(fresh);
            }
            clearAccountCaches();
            await api.reloadBroker();
            await reloadPositions();
          } catch (e) {
            setError(_toMessage(e));
          } finally {
            setReloadingSlot(null);
          }
        }
        cancelFlight();
        return;
      }
      if (status.state === "error" || status.state === "cancelled") {
        setError(status.error || "OAuth 授权未完成。");
        cancelFlight();
        return;
      }
      pollTimer.current = window.setTimeout(
        () => void pollOnce(f),
        OAUTH_POLL_INTERVAL_MS,
      );
    } catch (e) {
      setError(_toMessage(e));
      cancelFlight();
    }
  };

  /** Click handler for a slot: if already authorized → activate. Else
   *  start OAuth, tag the resulting account with the slot label. */
  const handleSlotClick = async (slot: SlotLabel) => {
    if (!form) return;
    const acct = slotAccount(form.accounts, slot);
    if (acct?.authorized) {
      await activateSlot(slot);
      return;
    }
    setError(null);
    if (flight !== null) cancelFlight();
    try {
      const start = await api.startLongportOauth();
      const f: OAuthFlight = {
        slot,
        sessionId: start.session_id,
        authUrl: start.auth_url,
        accountId: start.account_id,
        startedAt: Date.now(),
      };
      setFlight(f);
      window.open(start.auth_url, "_blank", "noopener,noreferrer");
      pollTimer.current = window.setTimeout(
        () => void pollOnce(f),
        OAUTH_POLL_INTERVAL_MS,
      );
    } catch (e) {
      setError(_toMessage(e));
    }
  };

  const handleLogout = async (slot: SlotLabel) => {
    if (!form) return;
    const acct = slotAccount(form.accounts, slot);
    if (!acct) return;
    setError(null);
    setBusySlot(slot);
    const wasActive = form.active_account_id === acct.account_id;
    try {
      const fresh = await api.logoutLongportAccount(acct.account_id);
      setForm(fresh);
      onSaved(fresh);
      if (wasActive) {
        clearAccountCaches();
        try {
          await api.reloadBroker();
        } catch (e) {
          console.warn("broker reload after logout failed:", e);
        }
        await reloadPositions();
      }
    } catch (e) {
      setError(_toMessage(e));
    } finally {
      setBusySlot(null);
    }
  };

  const handleRegionChange = (value: string) => {
    if (!form) return;
    setForm({ ...form, region: value });
    if (regionTimer.current !== null) window.clearTimeout(regionTimer.current);
    regionTimer.current = window.setTimeout(() => {
      void applyChange({ region: value });
    }, REGION_PATCH_DEBOUNCE_MS);
  };

  const renderSlot = (slot: SlotLabel) => {
    if (!form) return null;
    const acct = slotAccount(form.accounts, slot);
    const active = acct !== null && form.active_account_id === acct.account_id;
    const reloading = reloadingSlot === slot;
    const inFlight = flight?.slot === slot;
    const stateClass = inFlight
      ? "pending"
      : reloading
        ? "pending"
        : acct?.authorized
          ? "authed"
          : "unauthed";
    return (
      <button
        key={slot}
        type="button"
        className={`mode-btn ${stateClass} ${active ? "active" : ""}`}
        onClick={() => void handleSlotClick(slot)}
        title={
          inFlight
            ? "等待长桥授权完成…"
            : reloading
              ? "切换账户中…"
              : acct?.authorized
                ? `${slot.toUpperCase()} 已授权，点击切换`
                : `${slot.toUpperCase()} 未授权，点击后将打开长桥授权页`
        }
        disabled={reloadingSlot !== null && reloadingSlot !== slot}
      >
        <span className="dot" aria-hidden />
        <span className="mode-label">{slot}</span>
        <span className="mode-state">
          {reloading
            ? "切换中…"
            : inFlight
              ? "授权中…"
              : acct?.authorized
                ? "已授权"
                : "未授权"}
        </span>
      </button>
    );
  };

  return (
    <div className="lp-modal-backdrop" onClick={onClose}>
      <div className="lp-modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>LongPort 设置</h3>
          <button className="close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </header>

        <div className="lp-modal-body">
          {loading && <p className="hint">加载中…</p>}
          {!loading && form && (
            <>
              <section className="lp-panel">
                <label>长桥账户</label>
                <div className="mode-switch auth-aware">
                  {renderSlot("paper")}
                  {renderSlot("real")}
                </div>
                <p className="hint small">
                  paper / real 各对应一个独立的长桥账户（长桥 OpenAPI 不区分模拟盘）。
                  点击「已授权」的槽位切换 broker；点击「未授权」槽位会打开长桥 OAuth 页面，
                  授权完成后自动绑定并切换。
                </p>
                {(slotAccount(form.accounts, "paper")?.authorized ||
                  slotAccount(form.accounts, "real")?.authorized) && (
                  <div className="auth-revoke-row">
                    {slotAccount(form.accounts, "paper")?.authorized && (
                      <button
                        type="button"
                        className="auth-revoke"
                        onClick={() => void handleLogout("paper")}
                        disabled={busySlot === "paper"}
                      >
                        退出 paper 授权
                      </button>
                    )}
                    {slotAccount(form.accounts, "real")?.authorized && (
                      <button
                        type="button"
                        className="auth-revoke"
                        onClick={() => void handleLogout("real")}
                        disabled={busySlot === "real"}
                      >
                        退出 real 授权
                      </button>
                    )}
                  </div>
                )}
                {flight && (
                  <p className="hint small mono">
                    若浏览器未自动打开授权页，{" "}
                    <a href={flight.authUrl} target="_blank" rel="noreferrer noopener">
                      点这里手动打开
                    </a>
                  </p>
                )}
              </section>

              <section>
                <label>
                  <input
                    type="checkbox"
                    checked={form.auto_trade}
                    onChange={(e) => void applyChange({ auto_trade: e.target.checked })}
                  />
                  <span>自动交易</span>
                </label>
                <p className="hint small">
                  关闭后消息解析成功会显示“确认下单”按钮，点击后才会触发下单。
                </p>
              </section>
              <section>
                <label>
                  <input
                    type="checkbox"
                    checked={form.dry_run}
                    onChange={(e) => void applyChange({ dry_run: e.target.checked })}
                  />
                  <span>dry run 模式</span>
                </label>
              </section>
              <section className="lp-panel">
                <label>涨跌色彩</label>
                <div className="mode-switch color-pref">
                  <button
                    className={colorMode === "us" ? "active" : ""}
                    onClick={() => setColorMode("us")}
                    type="button"
                  >
                    <span className="cp-arr up-us">▲</span>
                    <span className="cp-arr down-us">▼</span>
                    <span className="cp-name">US · HK</span>
                  </button>
                  <button
                    className={colorMode === "cn" ? "active" : ""}
                    onClick={() => setColorMode("cn")}
                    type="button"
                  >
                    <span className="cp-arr up-cn">▲</span>
                    <span className="cp-arr down-cn">▼</span>
                    <span className="cp-name">A 股</span>
                  </button>
                </div>
                <p className="hint small">
                  仅影响图表与持仓卡片的方向色，本地保存，不写入 LongPort
                  服务端。切换立即生效。
                </p>
              </section>

              <section>
                <label htmlFor="lp-region">地区设置</label>
                <input
                  id="lp-region"
                  value={form.region}
                  onChange={(e) => handleRegionChange(e.target.value)}
                  placeholder="cn"
                />
              </section>
            </>
          )}
          {error && <div className="error">{error}</div>}
        </div>
      </div>
    </div>
  );
}
