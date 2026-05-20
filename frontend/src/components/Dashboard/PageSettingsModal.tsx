import { useState, useCallback, useEffect } from "react";
import type { WhopPage, WhopPageSettings, WhopPageSettingsPatch } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { OptionQuantityEditor } from "../common/OptionQuantityEditor";
import { AttachedMonitorsSection } from "./AttachedMonitorsSection";
import { useChildPagesStore } from "../../stores/childPages";
import "./PageSettingsModal.css";

interface Props {
  page: WhopPage;
  onClose: () => void;
}

const EMPTY_PAGES: WhopPage[] = [];

type ChatTab = "message" | "stock" | "option";

export function PageSettingsModal({ page, onClose }: Props) {
  const [dedupe, setDedupe] = useState(page.settings.dedupe_processed_messages);
  const [tolerance, setTolerance] = useState(String(page.settings.price_deviation_tolerance));
  const [blockHistorical, setBlockHistorical] = useState(page.settings.block_historical_messages);
  const [launchHeadless, setLaunchHeadless] = useState(Boolean(page.settings.launch_headless));
  const [parserV2, setParserV2] = useState(page.settings.parser_version === "v2");
  const [optionBuyQtyEnabled, setOptionBuyQtyEnabled] = useState(
    Boolean(page.settings.option_buy_quantity_enabled)
  );
  const [optionBuyQty, setOptionBuyQty] = useState(
    page.settings.option_buy_quantity != null ? String(page.settings.option_buy_quantity) : ""
  );
  const [optionTotalLimitEnabled, setOptionTotalLimitEnabled] = useState(
    Boolean(page.settings.option_total_price_limit_enabled)
  );
  const [optionTotalLimit, setOptionTotalLimit] = useState(
    page.settings.option_total_price_limit != null ? String(page.settings.option_total_price_limit) : ""
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);

  const isChat = page.source === "chat";
  const [chatTab, setChatTab] = useState<ChatTab>("message");

  // ── Child pages (chat-source only) ──────────────────────────────────────
  const childPages = useChildPagesStore((s) => s.byParent[page.id] ?? EMPTY_PAGES);
  const stockCount = childPages.filter((p) => p.source === "stock").length;
  const optionCount = childPages.filter((p) => p.source === "option").length;

  const refetchChildren = useCallback(async () => {
    try {
      const r = await api.listWhopPages({ parentChatId: page.id });
      useChildPagesStore.getState().setByParent(page.id, r.pages);
    } catch (e) {
      console.warn("refetch children failed:", e);
    }
  }, [page.id]);

  useEffect(() => {
    if (isChat) {
      refetchChildren();
    }
  }, [page.id, isChat, refetchChildren]);

  const handleClearHistory = async () => {
    if (!confirm(`确认从数据库删除 "${page.name}" 的所有历史消息？\n此操作不可逆，监听仍继续抓新消息。`)) return;
    setClearing(true);
    setError(null);
    try {
      const r = await api.cleanupPageHistory(page.url);
      useTasksStore.getState().removeTasksByUrl(page.url);
      alert(`已清理 ${r.deleted_count} 条历史消息`);
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
      setClearing(false);
    }
  };

  const initialDedupe = page.settings.dedupe_processed_messages;
  const dedupeChanged = dedupe !== initialDedupe;

  const handleSave = async () => {
    setError(null);

    // Chat-source has only dedupe + launch_headless — no tolerance / option fields
    // are rendered, so skip their validation entirely.
    if (isChat) {
      setSaving(true);
      try {
        const patch: WhopPageSettingsPatch = {
          dedupe_processed_messages: dedupe,
          launch_headless: launchHeadless,
        };
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
      return;
    }

    const tolNum = Number(tolerance);
    if (Number.isNaN(tolNum) || tolNum < 0) {
      setError("价格偏差必须 ≥ 0");
      return;
    }
    if (page.source === "option") {
      if (optionBuyQtyEnabled) {
        const optionQtyNum = Number(optionBuyQty);
        if (Number.isNaN(optionQtyNum) || optionQtyNum <= 0 || !Number.isInteger(optionQtyNum)) {
          setError("期权购买张数必须是 > 0 的整数");
          return;
        }
      }
      if (optionTotalLimitEnabled) {
        const optionTotalNum = Number(optionTotalLimit);
        if (Number.isNaN(optionTotalNum) || optionTotalNum <= 0) {
          setError("期权总价上限必须 > 0");
          return;
        }
      }
    }
    setSaving(true);
    try {
      const patch: Partial<WhopPageSettings> = {
        dedupe_processed_messages: dedupe,
        price_deviation_tolerance: tolNum,
        block_historical_messages: blockHistorical,
        launch_headless: launchHeadless,
        parser_version: parserV2 ? "v2" : "v1",
      };
      // Stock whitelist (tickers) is edited inline below the page header via
      // PageWhitelistBar — never include it here, so backend's per-field merge
      // keeps existing tickers untouched.
      if (page.source === "option") {
        patch.option_buy_quantity_enabled = optionBuyQtyEnabled;
        patch.option_buy_quantity = optionBuyQtyEnabled ? Number(optionBuyQty) : null;
        patch.option_total_price_limit_enabled = optionTotalLimitEnabled;
        patch.option_total_price_limit = optionTotalLimitEnabled ? Number(optionTotalLimit) : null;
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

  // ── Chat-source: only the message-tab needs the save+cancel footer. The
  // stock/option tabs are CRUD UIs that apply immediately, so we show only
  // "关闭". Non-chat sources keep the original save+cancel footer.
  const showSaveFooter = !isChat || chatTab === "message";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <header>
          <h3>{page.name} · 设置</h3>
          <button className="close" onClick={onClose} aria-label="关闭">✕</button>
        </header>

        {isChat && (
          <nav className="modal-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={chatTab === "message"}
              className={chatTab === "message" ? "active" : ""}
              onClick={() => setChatTab("message")}
            >
              消息监听
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={chatTab === "stock"}
              className={chatTab === "stock" ? "active" : ""}
              onClick={() => setChatTab("stock")}
            >
              正股监听<span className="tab-count">({stockCount})</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={chatTab === "option"}
              className={chatTab === "option" ? "active" : ""}
              onClick={() => setChatTab("option")}
            >
              期权监听<span className="tab-count">({optionCount})</span>
            </button>
          </nav>
        )}

        <div className="modal-body">
          {isChat ? (
            <>
              {chatTab === "message" && (
                <>
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
                    <label>
                      <input
                        type="checkbox"
                        checked={launchHeadless}
                        onChange={e => setLaunchHeadless(e.target.checked)}
                      />
                      <span>用无头模式启动网页（Headless）</span>
                    </label>
                    <p className="hint small">
                      重启监听后生效；关闭后会以可见浏览器窗口启动该页面监听。
                    </p>
                  </section>

                  <section className="danger-zone">
                    <h4>危险操作</h4>
                    <p className="hint small">
                      清空本聊天页的所有历史消息（消息 + 关联 task / 指令 / 推送事件全部从数据库删除）。监听本身不停，会继续抓新消息。
                    </p>
                    <button
                      type="button"
                      onClick={handleClearHistory}
                      disabled={clearing || saving}
                      className="danger-btn"
                    >
                      {clearing ? "清空中…" : "🗑 清空消息"}
                    </button>
                  </section>
                </>
              )}

              {chatTab === "stock" && (
                <AttachedMonitorsSection
                  parentId={page.id}
                  pages={childPages}
                  onRefresh={refetchChildren}
                  sourceFilter="stock"
                />
              )}

              {chatTab === "option" && (
                <AttachedMonitorsSection
                  parentId={page.id}
                  pages={childPages}
                  onRefresh={refetchChildren}
                  sourceFilter="option"
                />
              )}
            </>
          ) : (
            <>
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
                  自动下单时：买入若现价 &lt; 信号价 → 市价；否则限价 @ 信号价；卖出若现价 &gt; 信号价 → 市价；否则限价。
                  此百分比字段预留，当前不参与上述判断。
                </p>
              </section>

              <section>
                <label>
                  <input
                    type="checkbox"
                    checked={blockHistorical}
                    onChange={e => setBlockHistorical(e.target.checked)}
                  />
                  <span>禁止下单历史消息（消息发布时间早于本次监听启动时间）</span>
                </label>
                <p className="hint small">
                  消息 posted_at &lt; listener.started_at → 任务标记 SKIPPED（仅解析入库，不发送订单）。比"按当天/非当天"更细：当天但启动前发布的消息也会被拦。
                </p>
              </section>

              <section>
                <label>
                  <input
                    type="checkbox"
                    checked={launchHeadless}
                    onChange={e => setLaunchHeadless(e.target.checked)}
                  />
                  <span>用无头模式启动网页（Headless）</span>
                </label>
                <p className="hint small">
                  重启监听后生效；关闭后会以可见浏览器窗口启动该页面监听。
                </p>
              </section>

              <section>
                <label>
                  <input
                    type="checkbox"
                    checked={parserV2}
                    onChange={e => setParserV2(e.target.checked)}
                  />
                  <span>使用 parser v2（实验）</span>
                </label>
                <p className="hint small">
                  切换后下一条消息即用新 parser 解析，无需重启监听。默认关闭。
                </p>
              </section>

              {page.source === "option" && (
                <section>
                  <h4>期权购买数量配置</h4>
                  <OptionQuantityEditor
                    value={{
                      option_buy_quantity_enabled: optionBuyQtyEnabled,
                      option_buy_quantity: optionBuyQty === "" ? null : Number(optionBuyQty),
                      option_total_price_limit_enabled: optionTotalLimitEnabled,
                      option_total_price_limit: optionTotalLimit === "" ? null : Number(optionTotalLimit),
                    }}
                    onChange={(v) => {
                      setOptionBuyQtyEnabled(v.option_buy_quantity_enabled);
                      setOptionBuyQty(v.option_buy_quantity == null ? "" : String(v.option_buy_quantity));
                      setOptionTotalLimitEnabled(v.option_total_price_limit_enabled);
                      setOptionTotalLimit(v.option_total_price_limit == null ? "" : String(v.option_total_price_limit));
                    }}
                  />
                </section>
              )}

              <section className="danger-zone">
                <h4>危险操作</h4>
                <p className="hint small">
                  清空本页所有历史 task（任务 + 消息 + 指令 + 推送事件全部从数据库删除）。监听本身不停，会继续抓新消息。
                </p>
                <button
                  type="button"
                  onClick={handleClearHistory}
                  disabled={clearing || saving}
                  className="danger-btn"
                >
                  {clearing ? "清空中…" : "🗑 清空本页历史"}
                </button>
              </section>
            </>
          )}

          {error && <div className="error">{error}</div>}
        </div>

        <footer>
          {showSaveFooter ? (
            <>
              <button onClick={onClose}>取消</button>
              <button onClick={handleSave} disabled={saving || clearing} className="primary">
                {saving ? "保存中…" : "保存"}
              </button>
            </>
          ) : (
            <button onClick={onClose} className="primary">关闭</button>
          )}
        </footer>
      </div>
    </div>
  );
}
