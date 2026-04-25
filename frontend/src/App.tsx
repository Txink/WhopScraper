import { useState } from "react";
import { TopBar } from "./components/TopBar";
import { RightRail } from "./components/RightRail";
import { useStickyTop } from "./hooks/useStickyTop";
import "./App.css";

export default function App() {
  useStickyTop();
  // TODO Phase 9: actually call /api/health on mount. For now hardcode.
  const [conn] = useState({
    connWhop: "unknown" as const,
    connLongport: "unknown" as const,
    mode: "paper" as const,
    dryRun: true,
  });

  return (
    <div className="app">
      <TopBar {...conn} />
      <main className="main">
        <section className="stream">
          <div className="stream-head">
            <span>今日任务 · 0 条</span>
            <span>最新在上</span>
          </div>
          <div className="empty-state">
            <p>暂无任务。等待后端推送第一条消息…</p>
            <p className="hint">
              如果后端未运行：<code>cd backend && uv run uvicorn app.main:app --reload</code>
            </p>
          </div>
        </section>
        <RightRail />
      </main>
    </div>
  );
}
