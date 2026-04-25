import { useEffect, useRef, useState } from "react";
import { configureHttp, api, HttpError } from "./api/http";
import { createWsClient } from "./api/ws";
import { useConnStore } from "./stores/conn";
import { useTasksStore } from "./stores/tasks";
import { useStatsStore } from "./stores/stats";
import { usePositionsStore } from "./stores/positions";
import { TopBar } from "./components/TopBar";
import { RightRail } from "./components/RightRail";
import { Card } from "./components/Card/Card";
import { Login } from "./components/Login";
import { useStickyTop } from "./hooks/useStickyTop";
import type { TaskSummary, PushEvent } from "./api/domain-types";
import "./App.css";

// Config — BASE_URL from env or default; TOKEN resolved at runtime.
const BASE_URL = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/**
 * Token resolution priority:
 *  1. URL query param ?token=   (stores to localStorage and strips from URL)
 *  2. localStorage["APP_TOKEN"]
 *
 * Returns null if no token is found.
 */
function getStoredToken(): string | null {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem("APP_TOKEN", fromUrl);
    // Clean URL after persisting
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
    return fromUrl;
  }
  return localStorage.getItem("APP_TOKEN");
}

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

function handleLogout() {
  localStorage.removeItem("APP_TOKEN");
  window.location.reload();
}

function Dashboard({ token }: { token: string }) {
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
      token,
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
        onLogout={handleLogout}
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

export default function App() {
  const [authState, setAuthState] = useState<"checking" | "valid" | "missing" | "invalid">(
    "checking",
  );
  const [authError, setAuthError] = useState<string | undefined>();
  const [token, setToken] = useState<string>("");

  // First effect: validate token on mount
  useEffect(() => {
    const stored = getStoredToken();
    if (!stored) {
      setAuthState("missing");
      return;
    }
    setToken(stored);
    configureHttp({ baseUrl: BASE_URL, token: stored });
    api.health()
      .then(() => setAuthState("valid"))
      .catch((e: unknown) => {
        if (e instanceof HttpError && e.status === 403) {
          setAuthState("invalid");
          setAuthError("token 无效，请重新输入");
          // Clear bad token so login form renders fresh
          localStorage.removeItem("APP_TOKEN");
        } else {
          // Network error etc — assume valid and let normal flow handle it
          setAuthState("valid");
        }
      });
  }, []);

  if (authState === "checking") {
    return (
      <div className="login-screen">
        <p style={{ color: "var(--fg-3)" }}>检查登录中…</p>
      </div>
    );
  }
  if (authState === "missing" || authState === "invalid") {
    return <Login errorHint={authError} />;
  }

  // Valid token: render the dashboard
  return <Dashboard token={token} />;
}
