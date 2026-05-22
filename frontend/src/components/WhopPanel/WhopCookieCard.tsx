import { useEffect, useState } from "react";
import type { WhopCookieStatus } from "../../api/domain-types";
import { api } from "../../api/http";
import { fmtBeijingFull } from "../Card/cardHelpers";
import "./WhopCookieCard.css";

const LOGIN_COMMAND = "uv run --project backend python scripts/whop_login.py";

export function WhopCookieCard() {
  const [cookie, setCookie] = useState<WhopCookieStatus | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let alive = true;
    api.whopCookieStatus()
      .then((c) => { if (alive) setCookie(c); })
      .catch(() => { /* silent — card stays hidden if API unavailable */ });
    return () => { alive = false; };
  }, [refreshKey]);

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
    <section className="whop-cookie-card">
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
        <button onClick={() => setRefreshKey((k) => k + 1)} className="cookie-refresh">刷新</button>
        <CopyCommandButton command={LOGIN_COMMAND} />
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

function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s 前`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(0)}m 前`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h 前`;
  return `${(seconds / 86400).toFixed(1)}d 前`;
}
