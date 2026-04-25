import { useEffect } from "react";
import { configureHttp, api } from "./api/http";
import { createWsClient } from "./api/ws";
import { useConnStore } from "./stores/conn";
import { useTasksStore } from "./stores/tasks";
import { TopBar } from "./components/TopBar";
import { RightRail } from "./components/RightRail";
import { Card } from "./components/Card/Card";
import { useStickyTop } from "./hooks/useStickyTop";
import type { TaskSummary } from "./api/domain-types";
import "./App.css";

// Config — hardcoded for dev. Production: set via import.meta.env
const BASE_URL = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
const TOKEN = import.meta.env.VITE_APP_TOKEN ?? "dev-token";

/** Smart mode: decide whether a task renders expanded by default. */
function isActiveExpanded(task: TaskSummary): boolean {
  const activeStatus = [
    "RECEIVED", "PARSING", "INSTRUCTION_READY", "SUBMITTING",
    "PENDING", "PARTIAL",
  ];
  if (activeStatus.includes(task.status)) return true;
  // Recently-FILLED (<30s) stays expanded
  if (task.status === "FILLED") {
    const updatedAt = new Date(task.updated_at).getTime();
    return Date.now() - updatedAt < 30_000;
  }
  return false;
}

configureHttp({ baseUrl: BASE_URL, token: TOKEN });

export default function App() {
  useStickyTop();
  const conn = useConnStore();
  const tasks = useTasksStore((s) => s.tasks);
  const pushEventsByTask = useTasksStore((s) => s.pushEventsByTask);
  const applyWs = useTasksStore((s) => s.applyWsEvent);

  // On mount: fetch health + initial tasks; open WS
  useEffect(() => {
    let alive = true;

    // Initial health probe
    (async () => {
      try {
        const h = await api.health();
        if (alive) conn.setHealth(h);
      } catch (e) {
        console.warn("health fetch failed:", e);
      }
    })();

    // Initial task list
    (async () => {
      try {
        const resp = await api.listTasks({ limit: 100 });
        if (alive) {
          useTasksStore.getState().setInitialTasks(resp.tasks);
        }
      } catch (e) {
        console.warn("initial tasks fetch failed:", e);
      }
    })();

    // WebSocket
    const client = createWsClient({
      baseUrl: BASE_URL,
      token: TOKEN,
      onEvent: (evt) => {
        applyWs(evt);
        useConnStore.getState().setLastEventId(evt.event_id);
      },
      onStatus: (s) => useConnStore.getState().setWs(s),
    });
    client.connect();

    return () => {
      alive = false;
      client.disconnect();
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="app">
      <TopBar
        connWhop={conn.whop}
        connLongport={conn.longport}
        mode={conn.mode}
        dryRun={conn.dryRun}
      />
      <main className="main">
        <section className="stream">
          <div className="stream-head">
            <span>今日任务 · {tasks.length} 条</span>
            <span>最新在上</span>
          </div>
          {tasks.length === 0 ? (
            <div className="empty-state">
              <p>暂无任务。等待后端推送第一条消息…</p>
              <p className="hint">
                WebSocket 状态：<code>{conn.ws}</code>
              </p>
            </div>
          ) : (
            <>
              {tasks.map((t) => (
                <Card
                  key={t.id}
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  defaultExpanded={isActiveExpanded(t)}
                />
              ))}
            </>
          )}
        </section>
        <RightRail />
      </main>
    </div>
  );
}
