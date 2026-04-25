import { useEffect, useRef, useState } from "react";
import { configureHttp, api, HttpError } from "./api/http";
import { createWsClient } from "./api/ws";
import { useConnStore } from "./stores/conn";
import { useTasksStore } from "./stores/tasks";
import { useStatsStore } from "./stores/stats";
import { usePositionsStore } from "./stores/positions";
import { useViewStore } from "./stores/view";
import { usePageTabsStore } from "./stores/pageTabs";
import { TopBar } from "./components/TopBar";
import { RightRail } from "./components/RightRail";
import { Card } from "./components/Card/Card";
import { Login } from "./components/Login";
import { WhopPanel } from "./components/WhopPanel/WhopPanel";
import { useStickyTop } from "./hooks/useStickyTop";
import type { TaskSummary, PushEvent } from "./api/domain-types";
import "./App.css";

// Config — BASE_URL defaults to the page's origin so localhost / 127.0.0.1 /
// LAN-IP / etc all work without CORS. Override via VITE_API_BASE only when
// pointing the frontend at a different backend host (rare).
const BASE_URL = import.meta.env.VITE_API_BASE ?? window.location.origin;

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

/** Smart mode: decide whether a task renders expanded by default. */
function isActiveExpanded(task: TaskSummary): boolean {
  // Active statuses always expand
  if (ACTIVE_STATUSES.has(task.status)) return true;
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

function formatDateLabel(dateKey: string): string {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (dateKey === today) return `今天 ${dateKey}`;
  if (dateKey === yesterday) return `昨天 ${dateKey}`;
  return dateKey;
}

function DateGroups({ tasks, pushEventsByTask }: TaskGroupsProps) {
  // Sort tasks by message.posted_at desc (newest first)
  const sorted = [...tasks].sort((a, b) => {
    const aTime = a.message?.posted_at ?? a.created_at;
    const bTime = b.message?.posted_at ?? b.created_at;
    return bTime.localeCompare(aTime);
  });

  // Group by date string (YYYY-MM-DD) of posted_at
  const groups = new Map<string, TaskSummary[]>();
  for (const t of sorted) {
    const ts = t.message?.posted_at ?? t.created_at;
    const dateKey = ts.slice(0, 10); // "2026-04-25"
    if (!groups.has(dateKey)) groups.set(dateKey, []);
    groups.get(dateKey)!.push(t);
  }

  // Iterate in insertion order (desc due to sort above)
  const dateKeys = Array.from(groups.keys());

  return (
    <>
      {dateKeys.map((dateKey) => {
        const dayTasks = groups.get(dateKey)!;
        return (
          <div key={dateKey}>
            <div className="stream-divider">{formatDateLabel(dateKey)} · {dayTasks.length}</div>
            {dayTasks.map((t) => (
              <Card
                key={t.id}
                task={t}
                pushEvents={pushEventsByTask[t.id] ?? []}
                defaultExpanded={isActiveExpanded(t)}
              />
            ))}
          </div>
        );
      })}
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
        if (evt.type === "whop.page_changed") {
          usePageTabsStore.getState().applyPageChanged(evt);
        } else {
          applyWs(evt);
        }
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
          <DateGroups tasks={tasks} pushEventsByTask={pushEventsByTask} />
        )}
      </section>
      <RightRail />
    </main>
  );
}

function ContentRouter({ token }: { token: string }) {
  const view = useViewStore((s) => s.view);
  if (view === "whop") return <WhopPanel />;
  return <Dashboard token={token} />;
}

export default function App() {
  const [authState, setAuthState] = useState<"checking" | "valid" | "missing" | "invalid">(
    "checking",
  );
  const [authError, setAuthError] = useState<string | undefined>();
  const [token, setToken] = useState<string>("");
  const conn = useConnStore();

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
      .then((h) => {
        conn.setHealth(h);
        setAuthState("valid");
      })
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
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

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

  // Valid token: render with persistent TopBar + content router
  return (
    <div className="app">
      <TopBar
        connWhop={conn.whop}
        connLongport={conn.longport}
        mode={conn.mode}
        dryRun={conn.dryRun}
        onLogout={handleLogout}
      />
      <ContentRouter token={token} />
    </div>
  );
}
