import { useEffect, useState } from "react";
import { api, HttpError } from "../../api/http";
import type { LongportSettings } from "../../api/domain-types";
import "./LongportSettingsModal.css";

interface Props {
  onClose: () => void;
  onSaved: (settings: LongportSettings) => void;
}

export function LongportSettingsModal({ onClose, onSaved }: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<LongportSettings | null>(null);

  useEffect(() => {
    let alive = true;
    api.getLongportSettings()
      .then((settings) => {
        if (!alive) return;
        setForm(settings);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        if (e instanceof HttpError) {
          setError(typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail: unknown }).detail)
            : e.message);
        } else {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => { alive = false; };
  }, []);

  const updateCredentialField = (
    mode: "paper" | "real",
    key: "app_key" | "app_secret" | "access_token",
    value: string,
  ) => {
    if (!form) return;
    setForm({
      ...form,
      [mode]: {
        ...form[mode],
        [key]: value,
      },
    });
  };

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.updateLongportSettings({
        mode: form.mode,
        paper: form.paper,
        real: form.real,
        auto_trade: form.auto_trade,
        region: form.region,
        dry_run: form.dry_run,
      });
      onSaved(saved);
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

  return (
    <div className="lp-modal-backdrop" onClick={onClose}>
      <div className="lp-modal" onClick={(e) => e.stopPropagation()}>
        <header>
          <h3>LongPort 设置</h3>
          <button className="close" onClick={onClose} aria-label="关闭">✕</button>
        </header>

        <div className="lp-modal-body">
          {loading && <p className="hint">加载中…</p>}
          {!loading && form && (
            <>
              <section>
                <label>
                  <input
                    type="checkbox"
                    checked={form.auto_trade}
                    onChange={(e) => setForm({ ...form, auto_trade: e.target.checked })}
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
                    onChange={(e) => setForm({ ...form, dry_run: e.target.checked })}
                  />
                  <span>dry run 模式</span>
                </label>
              </section>
              <section className="lp-panel">
                <label>当前模式</label>
                <div className="mode-switch">
                  <button
                    className={form.mode === "paper" ? "active" : ""}
                    onClick={() => setForm({ ...form, mode: "paper" })}
                    type="button"
                  >
                    paper
                  </button>
                  <button
                    className={form.mode === "real" ? "active" : ""}
                    onClick={() => setForm({ ...form, mode: "real" })}
                    type="button"
                  >
                    real
                  </button>
                </div>
                <p className="hint small">
                  当前模式会同时决定下方正在编辑的密钥组。
                </p>
              </section>

              <section className="lp-panel">
                <label>{form.mode.toUpperCase()} 密钥</label>
                <div className="cred-grid">
                  <label htmlFor="lp-app-key">appKey</label>
                  <input
                    id="lp-app-key"
                    value={form[form.mode].app_key}
                    onChange={(e) => updateCredentialField(form.mode, "app_key", e.target.value)}
                    placeholder={`${form.mode} appKey`}
                  />
                  <label htmlFor="lp-app-secret">appSecret</label>
                  <input
                    id="lp-app-secret"
                    value={form[form.mode].app_secret}
                    onChange={(e) => updateCredentialField(form.mode, "app_secret", e.target.value)}
                    placeholder={`${form.mode} appSecret`}
                  />
                  <label htmlFor="lp-access-token">accessToken</label>
                  <input
                    id="lp-access-token"
                    value={form[form.mode].access_token}
                    onChange={(e) => updateCredentialField(form.mode, "access_token", e.target.value)}
                    placeholder={`${form.mode} accessToken`}
                  />
                </div>
              </section>
              <section>
                <label htmlFor="lp-region">地区设置</label>
                <input
                  id="lp-region"
                  value={form.region}
                  onChange={(e) => setForm({ ...form, region: e.target.value })}
                  placeholder="cn"
                />
              </section>
            </>
          )}
          {error && <div className="error">{error}</div>}
        </div>

        <footer>
          <button onClick={onClose}>取消</button>
          <button onClick={handleSave} disabled={loading || saving || !form} className="primary">
            {saving ? "保存中…" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
