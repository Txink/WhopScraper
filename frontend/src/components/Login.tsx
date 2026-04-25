import { useState } from "react";
import "./Login.css";

interface LoginProps {
  errorHint?: string; // shown above input when redirected here from a 403
}

export function Login({ errorHint }: LoginProps) {
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setSubmitting(true);
    localStorage.setItem("APP_TOKEN", value.trim());
    // Strip ?token= from URL if present, then reload to apply new token
    const url = new URL(window.location.href);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
    window.location.reload();
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-brand">
          <span className="dot"></span>
          <h1>Signal Station</h1>
        </div>
        <p className="login-subtitle">whop → longport · 监控看板</p>
        {errorHint && <div className="login-error">{errorHint}</div>}
        <form onSubmit={handleSubmit}>
          <label className="login-label" htmlFor="token-input">
            APP TOKEN
          </label>
          <input
            id="token-input"
            type="password"
            placeholder="32 字符 token（来自 .env 文件 APP_TOKEN）"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            className="login-input"
          />
          <button
            type="submit"
            disabled={submitting || !value.trim()}
            className="login-button"
          >
            {submitting ? "进入中..." : "进入"}
          </button>
        </form>
        <p className="login-hint">
          token 保存在浏览器 localStorage 后续无需重输。
          <br />
          也可使用 <code>?token=...</code> URL 参数一次性进入。
        </p>
      </div>
    </div>
  );
}
