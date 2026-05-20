import { useState } from "react";
import type { WhopPage, WhopPageSettingsPatch, TickerConfig } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
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
        </div>
      )}
    </div>
  );
}
