import { useState, useCallback, useEffect } from "react";
import type { WhopPage, WhopPageSettings, WhopPageSettingsPatch } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { AttachedMonitorsSection } from "./AttachedMonitorsSection";
import { WhopCookieCard } from "../WhopPanel/WhopCookieCard";
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
  const [launchHeadless, setLaunchHeadless] = useState(Boolean(page.settings.launch_headless));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);

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
    refetchChildren();
  }, [page.id, refetchChildren]);

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
  };

  // Only the message-tab needs the save+cancel footer. The stock/option
  // tabs apply changes immediately via AttachedMonitorsSection, so we show
  // only "关闭".
  const showSaveFooter = chatTab === "message";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <header>
          <h3>{page.name} · 设置</h3>
          <button className="close" onClick={onClose} aria-label="关闭">✕</button>
        </header>

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

        <div className="modal-body">
          {chatTab === "message" && (
            <>
              <WhopCookieCard />

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

          {error && <div className="modal-error">{error}</div>}
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
