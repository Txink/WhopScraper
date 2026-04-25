import { useEffect, useRef } from "react";
import { configureHttp, api } from "./api/http";
import { createWsClient } from "./api/ws";
import { useConnStore } from "./stores/conn";
import { useTasksStore } from "./stores/tasks";
import { useStatsStore } from "./stores/stats";
import { usePositionsStore } from "./stores/positions";
import { TopBar } from "./components/TopBar";
import { RightRail } from "./components/RightRail";
import { Card } from "./components/Card/Card";
import { useStickyTop } from "./hooks/useStickyTop";
import type { TaskSummary, PushEvent } from "./api/domain-types";
import "./App.css";

// Config — BASE_URL from env or default; TOKEN resolved at runtime.
const BASE_URL = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * Token resolution priority:
 *  1. URL query param ?token=   (stores to localStorage for future loads)
 *  2. localStorage["APP_TOKEN"]
 *  3. VITE_APP_TOKEN build-time env var
 *  4. "dev-token" fallback
 *
 * Usage: open http://localhost:8000?token=your-token once; subsequent
 * page loads pick it from localStorage without needing the query param.
 */
function getToken(): string {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem("APP_TOKEN", fromUrl);
    return fromUrl;
  }
  const stored = localStorage.getItem("APP_TOKEN");
  if (stored) return stored;
  return import.meta.env.VITE_APP_TOKEN ?? "dev-token";
}

const TOKEN = getToken();

const ACTIVE_STATUSES = new Set([
  "RECEIVED", "PARSING", "INSTRUCTION_READY",
  "SUBMITTING", "PENDING", "PARTIAL",
]);

/** Smart mode: decide whether a history task renders expanded by default. */
function isActiveExpanded(task: TaskSummary): boolean {
  // Recently-FILLED (<30s) stays expanded
  if (task.status === "FILLED") {
    const updatedAt = new Date(task.updated_at).getTime();
    return Date.now() - updatedAt < 30_000;
  }
  return false;
}

async function refreshStats() {
  try {
    const s = await api.stats();
    useStatsStore.getState().setStats(s);
  } catch (e) {
    console.warn("stats fetch failed:", e);
  }
}

async function refreshPositions() {
  try {
    const p = await api.positions();
    usePositionsStore.getState().setAll(p);
  } catch (e) {
    console.warn("positions fetch failed:", e);
  }
}

configureHttp({ baseUrl: BASE_URL, token: TOKEN });

interface TaskGroupsProps {
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
}

function TaskGroups({ tasks, pushEventsByTask }: TaskGroupsProps) {
  const active = tasks.filter((t) => ACTIVE_STATUSES.has(t.status));
  const history = tasks.filter((t) => !ACTIVE_STATUSES.has(t.status));

  return (
    <>
      {active.length > 0 && (
        <>
          <div className="stream-divider">进行中 · {active.length}</div>
          {active.map((t) => (
            <Card
              key={t.id}
              task={t}
              pushEvents={pushEventsByTask[t.id] ?? []}
              defaultExpanded={true}
            />
          ))}
        </>
      )}
      {history.length > 0 && (
        <>
          <div className="stream-divider">已完成 · {history.length}</div>
          {history.map((t) => (
            <Card
              key={t.id}
              task={t}
              pushEvents={pushEventsByTask[t.id] ?? []}
              defaultExpanded={isActiveExpanded(t)}
            />
          ))}
        </>
      )}
    </>
  );
}

export default function App() {
  useStickyTop();
  const conn = useConnStore();
  const tasks = useTasksStore((s) => s.tasks);
  const pushEventsByTask = useTasksStore((s) => s.pushEventsByTask);
  const applyWs = useTasksStore((s) => s.applyWsEvent);

  // Refetch stats + positions on WS reconnect (closed → open)
  const prevWsRef = useRef<typeof conn.ws>("closed");
  useEffect(() => {
    const shouldRefresh =
      conn.ws === "open" && prevWsRef.current !== "open";
    prevWsRef.current = conn.ws;
    if (!shouldRefresh) return;
    refreshStats();
    refreshPositions();
  }, [conn.ws]);

  // On mount: fetch health + initial tasks; open WS; fetch stats + positions
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

    // Initial stats + positions
    refreshStats();
    refreshPositions();

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
            <TaskGroups tasks={tasks} pushEventsByTask={pushEventsByTask} />
          )}
        </section>
        <RightRail />
      </main>
    </div>
  );
}
