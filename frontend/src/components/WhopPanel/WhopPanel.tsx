import { useEffect, useState } from "react";
import type { WhopPage, WhopCookieStatus } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { fmtBeijingFull } from "../Card/cardHelpers";
import "./WhopPanel.css";

export function WhopPanel() {
  const [pages, setPages] = useState<WhopPage[]>([]);
  const [cookie, setCookie] = useState<WhopCookieStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([api.listWhopPages(), api.whopCookieStatus()])
      .then(([p, c]) => {
        if (!alive) return;
        setPages(p.pages);
        setCookie(c);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, [refreshKey]);

  const refresh = () => setRefreshKey((k) => k + 1);

  return (
    <section className="whop-panel">
      <CookieSection cookie={cookie} onRefresh={refresh} />
      <AddPageSection onAdded={refresh} />
      <PagesListSection pages={pages} loading={loading} onRefresh={refresh} error={error} />
    </section>
  );
}

// Sub-components below:

function CookieSection({ cookie, onRefresh }: { cookie: WhopCookieStatus | null; onRefresh: () => void }) {
  if (!cookie) return null;

  let statusClass = "cookie-status";
  let statusLabel = "未知";
  if (!cookie.exists) {
    statusClass = "cookie-status missing";
    statusLabel = "缺失";
  } else if (cookie.age_seconds != null && cookie.age_seconds > 14 * 86400) {
    statusClass = "cookie-status stale";
    statusLabel = "过期可能";
  } else {
    statusClass = "cookie-status ok";
    statusLabel = "有效";
  }

  const ageStr = cookie.age_seconds != null ? formatAge(cookie.age_seconds) : "-";
  const lastMod = cookie.last_modified ? fmtBeijingFull(cookie.last_modified) : "-";

  return (
    <section className="panel-card">
      <h3>Whop Cookie 状态</h3>
      <div className="cookie-row">
        <span className="cookie-label">状态</span>
        <span className={statusClass}>{statusLabel}</span>
      </div>
      <div className="cookie-row">
        <span className="cookie-label">文件路径</span>
        <code className="cookie-path">{cookie.path}</code>
      </div>
      <div className="cookie-row">
        <span className="cookie-label">最后修改</span>
        <span className="cookie-mtime">{lastMod} ({ageStr})</span>
      </div>
      <div className="cookie-actions">
        <button onClick={onRefresh} className="cookie-refresh">刷新</button>
        <CopyCommandButton command="uv run --project backend python scripts/whop_login.py" />
      </div>
      <p className="cookie-hint">
        Cookie 缺失或过期时，复制上面的命令在终端运行：会打开浏览器让你手动登录 Whop，
        登录完毕回终端按回车后 cookie 自动保存。
      </p>
    </section>
  );
}

function CopyCommandButton({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("复制下面的命令", command);
    }
  };
  return (
    <button onClick={handleCopy} className="copy-cmd-btn" title={command}>
      {copied ? "已复制 ✓" : "复制登录命令"}
    </button>
  );
}

function AddPageSection({ onAdded }: { onAdded: () => void }) {
  const [url, setUrl] = useState("");
  const [source, setSource] = useState<"stock" | "option" | "chat">("stock");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.addWhopPage({
        url: url.trim(),
        source,
        name: name.trim() || null,
      });
      setUrl("");
      setName("");
      onAdded();
    } catch (e) {
      if (e instanceof HttpError) {
        setError(typeof e.body === "object" && e.body && "detail" in e.body
          ? String((e.body as { detail: unknown }).detail)
          : e.message);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel-card">
      <h3>添加监听</h3>
      <form className="add-page-form" onSubmit={handleSubmit}>
        <div className="form-row">
          <label>
            <span>URL</span>
            <input
              type="text"
              placeholder="https://whop.com/joined/<channel>/app/"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="add-input mono"
              disabled={submitting}
            />
          </label>
        </div>
        <div className="form-row two-col">
          <label>
            <span>来源类型</span>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value as "stock" | "option" | "chat")}
              className="add-select"
              disabled={submitting}
            >
              <option value="stock">正股 (stock)</option>
              <option value="option">期权 (option)</option>
              <option value="chat">聊天 (chat)</option>
            </select>
          </label>
          <label>
            <span>显示名 (可选)</span>
            <input
              type="text"
              placeholder="自动用 URL"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="add-input"
              disabled={submitting}
            />
          </label>
        </div>
        {error && <div className="add-error">{error}</div>}
        <button type="submit" disabled={submitting || !url.trim()} className="add-submit">
          {submitting ? "添加中..." : "添加监听"}
        </button>
      </form>
    </section>
  );
}

function PagesListSection({ pages, loading, error, onRefresh }: {
  pages: WhopPage[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  return (
    <section className="panel-card">
      <h3>监听列表 <span className="count">{pages.length}</span></h3>
      {error && <div className="page-error">{error}</div>}
      {loading && pages.length === 0 ? (
        <p className="empty-hint">加载中...</p>
      ) : pages.length === 0 ? (
        <p className="empty-hint">暂无监听。从上面的"添加监听"开始。</p>
      ) : (
        <table className="pages-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>名称</th>
              <th>URL</th>
              <th>状态</th>
              <th>最后轮询</th>
              <th>已发消息</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <PageRow key={p.id} page={p} onRefresh={onRefresh} />
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function PageRow({ page, onRefresh }: { page: WhopPage; onRefresh: () => void }) {
  const [acting, setActing] = useState(false);

  const handleRemove = async () => {
    if (!confirm(`确认移除 "${page.name}" 吗？`)) return;
    setActing(true);
    try {
      await api.removeWhopPage(page.id);
      onRefresh();
    } catch (e) {
      alert(`移除失败：${e instanceof Error ? e.message : e}`);
    } finally {
      setActing(false);
    }
  };

  const handleRestart = async () => {
    setActing(true);
    try {
      await api.restartWhopPage(page.id);
      onRefresh();
    } catch (e) {
      alert(`重启失败：${e instanceof Error ? e.message : e}`);
    } finally {
      setActing(false);
    }
  };

  let statusEl: React.ReactNode;
  if (page.last_error) {
    statusEl = <span className="page-status error" title={page.last_error}>错误</span>;
  } else if (page.running) {
    statusEl = <span className="page-status running">运行中</span>;
  } else {
    statusEl = <span className="page-status stopped">未运行</span>;
  }

  const lastPoll = page.last_poll_at ? formatRelative(page.last_poll_at) : "—";

  return (
    <tr>
      <td>
        <span className={`type-badge ${page.source}`}>
          {page.source === "stock" ? "正股" : page.source === "option" ? "期权" : "聊天"}
        </span>
      </td>
      <td className="cell-name">{page.name}</td>
      <td className="cell-url" title={page.url}>{page.url}</td>
      <td>{statusEl}</td>
      <td className="cell-mono">{lastPoll}</td>
      <td className="cell-mono cell-num">{page.messages_published}</td>
      <td className="cell-actions">
        <button onClick={handleRestart} disabled={acting} className="action-btn">重启</button>
        <button onClick={handleRemove} disabled={acting} className="action-btn danger">移除</button>
      </td>
    </tr>
  );
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s 前`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(0)}m 前`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h 前`;
  return `${(seconds / 86400).toFixed(1)}d 前`;
}

function formatRelative(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "—";
  return formatAge(ms / 1000);
}
