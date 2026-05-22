import { useState } from "react";
import type {
  WhopPage,
  WhopPageSettings,
  WhopPageSettingsPatch,
  TickerConfig,
} from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { TickerWhitelistEditor } from "../common/TickerWhitelistEditor";
import { OptionQuantityEditor } from "../common/OptionQuantityEditor";
import "./AttachedMonitorsSection.css";

interface Props {
  parentId: string;
  /** Child monitor pages attached to this chat page. Named `pages` (not
   * `children`) to avoid shadowing React's implicit children prop. */
  pages: WhopPage[];
  onRefresh(): void;
  /** When set, the component is in single-source mode: pages are filtered
   *  to this source, the source dropdown in the add-form is hidden, and
   *  copy is tailored. Used by the tabbed chat-source settings modal. */
  sourceFilter?: "stock" | "option";
}

export function AttachedMonitorsSection({ parentId, pages, onRefresh, sourceFilter }: Props) {
  const filtered = sourceFilter ? pages.filter((p) => p.source === sourceFilter) : pages;

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [addForm, setAddForm] = useState<{ url: string; source: "stock" | "option"; name: string }>({
    url: "",
    source: sourceFilter ?? "stock",
    name: "",
  });
  const [addErr, setAddErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddErr(null);
    setSubmitting(true);
    try {
      await api.addWhopPage({
        url: addForm.url.trim(),
        source: addForm.source,
        name: addForm.name.trim() || null,
        parent_chat_id: parentId,
      });
      setAddForm({ url: "", source: sourceFilter ?? "stock", name: "" });
      onRefresh();
    } catch (e) {
      setAddErr(e instanceof HttpError ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const sourceLabel =
    sourceFilter === "stock" ? "正股" : sourceFilter === "option" ? "期权" : "";

  return (
    <section className="attached-monitors">
      {sourceFilter ? (
        <p className="hint small">
          管理本聊天页关联的{sourceLabel}监听 — 每个 URL 对应一个 sender，
          {sourceLabel}信号会以信号卡形式出现在聊天列表里。
          <span className="count" style={{ marginLeft: 8 }}>{filtered.length} 个</span>
        </p>
      ) : (
        <>
          <h4>
            挂载监听 <span className="count">{filtered.length} 个</span>
          </h4>
          <p className="hint small">
            从这里管理本聊天页关联的正股 / 期权监听 — 每个 URL 对应一个 sender，消息会以信号卡形式出现在聊天列表里。
          </p>
        </>
      )}

      <div className="mon-list">
        {filtered.map((page) => (
          <MonRow
            key={page.id}
            page={page}
            expanded={expandedId === page.id}
            onToggle={() => setExpandedId((curr) => (curr === page.id ? null : page.id))}
            onRefresh={onRefresh}
          />
        ))}
      </div>

      <form className="mon-add-form" onSubmit={handleAdd}>
        <div className="add-title">添加{sourceLabel}监听</div>
        <input
          type="url"
          placeholder="https://whop.com/joined/<channel>/app/"
          value={addForm.url}
          onChange={(e) => setAddForm({ ...addForm, url: e.target.value })}
          required
          disabled={submitting}
        />
        {sourceFilter ? (
          <input
            type="text"
            placeholder={`名称（如：${sourceFilter === "option" ? "NVDA 期权" : "TSLL"} 监听）`}
            value={addForm.name}
            onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
            disabled={submitting}
          />
        ) : (
          <div className="add-row">
            <select
              value={addForm.source}
              onChange={(e) =>
                setAddForm({ ...addForm, source: e.target.value as "stock" | "option" })
              }
              disabled={submitting}
            >
              <option value="stock">正股 (stock)</option>
              <option value="option">期权 (option)</option>
              <option value="chat" disabled>
                聊天 (chat) — 子监听不可
              </option>
            </select>
            <input
              type="text"
              placeholder="名称（如：TSLL 监听）"
              value={addForm.name}
              onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
              disabled={submitting}
            />
          </div>
        )}
        {addErr && <div className="add-error">{addErr}</div>}
        <button
          type="submit"
          className="btn primary"
          disabled={submitting || !addForm.url.trim()}
        >
          {submitting ? "添加中..." : `+ 添加${sourceLabel}监听`}
        </button>
      </form>
    </section>
  );
}

// ─────────────────────────── MonRow ───────────────────────────────────────

interface RowProps {
  page: WhopPage;
  expanded: boolean;
  onToggle(): void;
  onRefresh(): void;
}

function MonRow({ page, expanded, onToggle, onRefresh }: RowProps) {
  const [acting, setActing] = useState(false);

  const guard = async (fn: () => Promise<unknown>) => {
    setActing(true);
    try {
      await fn();
      onRefresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const isRunning = page.running;
  const isError = Boolean(page.last_error);
  const sourceCls = page.source as "stock" | "option";

  const rowCls = [
    "mon-row",
    sourceCls,
    expanded ? "expanded" : "",
    isError ? "error" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rowCls}>
      <div
        className="mon-head"
        onClick={(e) => {
          if ((e.target as HTMLElement).closest(".mon-btn")) return;
          onToggle();
        }}
      >
        <span className={`src-dot ${sourceCls}`} />
        <span className={`type-chip ${sourceCls}`}>
          {sourceCls === "stock" ? "正股" : "期权"}
        </span>
        <span className="mon-name">{page.name}</span>
        <span className="mon-url" title={page.url}>
          {page.url}
        </span>
        <span className="mon-actions">
          <span
            className={`mon-status ${isError ? "error" : isRunning ? "running" : "stopped"}`}
          >
            <span className="state-dot" />
            {isError ? "错误" : isRunning ? "运行中" : "已停"}
          </span>
          <button
            type="button"
            className="mon-btn icon-only"
            disabled={acting}
            title={isRunning ? "停止" : "启动"}
            onClick={(e) => {
              e.stopPropagation();
              guard(() =>
                isRunning ? api.stopWhopPage(page.id) : api.startWhopPage(page.id)
              );
            }}
          >
            {isRunning ? "⏸" : "▶"}
          </button>
          <button
            type="button"
            className="mon-btn icon-only"
            disabled={acting}
            title="重启"
            onClick={(e) => {
              e.stopPropagation();
              guard(() => api.restartWhopPage(page.id));
            }}
          >
            ↻
          </button>
          <button
            type="button"
            className="mon-btn icon-only danger"
            disabled={acting}
            title="移除"
            onClick={(e) => {
              e.stopPropagation();
              if (!confirm(`确认移除 "${page.name}"？`)) return;
              guard(() => api.removeWhopPage(page.id));
            }}
          >
            ✕
          </button>
          <span className="mon-expand" aria-hidden="true">
            ▾
          </span>
        </span>
      </div>

      {expanded && (
        <div className="mon-body">
          {isError && page.last_error && (
            <div className="error-banner">
              <span className="glyph">!</span>
              <span>
                <b>last_error:</b> {page.last_error}
              </span>
            </div>
          )}

          {page.source === "stock" && (
            <div className="editor-block">
              <div className="editor-label">Ticker 白名单</div>
              {/* Reuse `.page-whitelist-bar` so chip/+button styles defined in
               * Dashboard.css apply here too. `.embedded` modifier strips the
               * dashed border-top that only makes sense under a page header. */}
              <div className="page-whitelist-bar embedded">
                <TickerWhitelistEditor
                  tickers={(page.settings.tickers ?? {}) as Record<string, TickerConfig>}
                  onChange={(next) =>
                    api
                      .updateWhopPageSettings(page.id, {
                        tickers: next,
                      } as WhopPageSettingsPatch)
                      .then(onRefresh)
                      .catch((e) => alert(e instanceof Error ? e.message : String(e)))
                  }
                />
              </div>
            </div>
          )}

          {page.source === "option" && (
            <div className="editor-block">
              <div className="editor-label">期权购买数量配置</div>
              <OptionQuantityEditor
                value={{
                  option_buy_quantity_enabled: Boolean(
                    page.settings.option_buy_quantity_enabled
                  ),
                  option_buy_quantity: page.settings.option_buy_quantity ?? null,
                  option_total_price_limit_enabled: Boolean(
                    page.settings.option_total_price_limit_enabled
                  ),
                  option_total_price_limit:
                    page.settings.option_total_price_limit ?? null,
                }}
                onChange={(v) =>
                  api
                    .updateWhopPageSettings(page.id, v as WhopPageSettingsPatch)
                    .then(onRefresh)
                    .catch((e) => alert(e instanceof Error ? e.message : String(e)))
                }
              />
            </div>
          )}

          <MonRowSettings page={page} onRefresh={onRefresh} />
        </div>
      )}
    </div>
  );
}

// ─── MonRow inline settings (migrated from the old per-page settings modal) ──

function MonRowSettings({ page, onRefresh }: { page: WhopPage; onRefresh(): void }) {
  const s = page.settings;
  const [tolerance, setTolerance] = useState<string>(String(s.price_deviation_tolerance ?? 0));
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const patch = async (p: WhopPageSettingsPatch) => {
    setError(null);
    try {
      await api.updateWhopPageSettings(page.id, p as WhopPageSettings);
      onRefresh();
    } catch (e) {
      setError(e instanceof HttpError ? e.message : (e instanceof Error ? e.message : String(e)));
    }
  };

  const commitTolerance = () => {
    if (tolerance === String(s.price_deviation_tolerance)) return;
    const n = Number(tolerance);
    if (Number.isNaN(n) || n < 0) {
      setError("价格偏差必须 ≥ 0");
      setTolerance(String(s.price_deviation_tolerance));
      return;
    }
    patch({ price_deviation_tolerance: n });
  };

  const handleClearHistory = async () => {
    if (!confirm(`确认从数据库删除 "${page.name}" 的所有历史 task？\n此操作不可逆，监听仍继续抓新消息。`)) return;
    setClearing(true);
    setError(null);
    try {
      const r = await api.cleanupPageHistory(page.url);
      useTasksStore.getState().removeTasksByUrl(page.url);
      alert(`已清理 ${r.deleted_count} 条历史 task`);
      onRefresh();
    } catch (e) {
      setError(e instanceof HttpError ? e.message : (e instanceof Error ? e.message : String(e)));
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="mon-settings">
      <label className="mon-setting-toggle">
        <input
          type="checkbox"
          checked={s.dedupe_processed_messages}
          onChange={(e) => patch({ dedupe_processed_messages: e.target.checked })}
        />
        <span>避免重复解析消息（启动 / 重启时跳过 DB 中已存在的 domID）</span>
      </label>

      <div className="mon-setting-field">
        <span className="mon-setting-label">价格偏差容忍 (%)</span>
        <input
          type="number"
          min={0}
          step={0.1}
          value={tolerance}
          onChange={(e) => setTolerance(e.target.value)}
          onBlur={commitTolerance}
          className="mon-setting-input"
        />
        <p className="hint small">字段预留，目前不参与买入 / 卖出市价限价判断。</p>
      </div>

      <label className="mon-setting-toggle">
        <input
          type="checkbox"
          checked={s.block_historical_messages}
          onChange={(e) => patch({ block_historical_messages: e.target.checked })}
        />
        <span>禁止下单历史消息（消息发布时间早于本次监听启动）</span>
      </label>

      <label className="mon-setting-toggle">
        <input
          type="checkbox"
          checked={Boolean(s.launch_headless)}
          onChange={(e) => patch({ launch_headless: e.target.checked })}
        />
        <span>用无头模式启动网页（Headless）— 重启监听后生效</span>
      </label>

      <label className="mon-setting-toggle">
        <input
          type="checkbox"
          checked={s.parser_version === "v2"}
          onChange={(e) => patch({ parser_version: e.target.checked ? "v2" : "v1" })}
        />
        <span>使用 parser v2（实验）</span>
      </label>

      <div className="mon-danger-zone">
        <button
          type="button"
          className="mon-btn danger"
          disabled={clearing}
          onClick={handleClearHistory}
        >
          {clearing ? "清空中…" : "🗑 清空本页历史"}
        </button>
        <span className="hint small">清空后监听不停，仍会继续抓新消息。</span>
      </div>

      {error && <div className="add-error">{error}</div>}
    </div>
  );
}
