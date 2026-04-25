import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactElement } from "react";
import { configureHttp, api, HttpError } from "./api/http";
import { createWsClient } from "./api/ws";
import { useConnStore } from "./stores/conn";
import { useTasksStore, selectTasksByUrl } from "./stores/tasks";
import { useStatsStore } from "./stores/stats";
import { usePositionsStore } from "./stores/positions";
import { useViewStore } from "./stores/view";
import { usePageTabsStore } from "./stores/pageTabs";
import { TopBar } from "./components/TopBar";
import { RightRail } from "./components/RightRail";
import { Login } from "./components/Login";
import { WhopPanel } from "./components/WhopPanel/WhopPanel";
import { PageTabs } from "./components/Dashboard/PageTabs";
import { PageInfoBar } from "./components/Dashboard/PageInfoBar";
import { PageActionBar } from "./components/Dashboard/PageActionBar";
import { TaskStream } from "./components/Dashboard/TaskStream";
import { EmptyState } from "./components/Dashboard/EmptyState";
import { useStickyTop } from "./hooks/useStickyTop";
import "./App.css";
import "./components/Dashboard/Dashboard.css";

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

function handleLogout() {
  localStorage.removeItem("APP_TOKEN");
  window.location.reload();
}

// Stub — replaced by real component in Task N.
// Kept here so the conditional render in Dashboard typechecks today.
function PageSettingsModal(_: { page: unknown; onClose: () => void }): ReactElement | null {
  return null;
}

function Dashboard({ token }: { token: string }) {
  useStickyTop();
  const conn = useConnStore();
  const tasks = useTasksStore((s) => s.tasks);
  const pushEventsByTask = useTasksStore((s) => s.pushEventsByTask);
  const applyWs = useTasksStore((s) => s.applyWsEvent);

  const pages = usePageTabsStore((s) => s.pages);
  const activeTabId = usePageTabsStore((s) => s.activeTabId);
  const setPages = usePageTabsStore((s) => s.setPages);
  const setOrphanCount = usePageTabsStore((s) => s.setOrphanCount);
  const expandMode = usePageTabsStore((s) =>
    activeTabId ? (s.expandModeByTab[activeTabId] ?? "smart") : "smart",
  );
  const orphanCount = usePageTabsStore((s) => s.orphanCount);

  const [settingsOpen, setSettingsOpen] = useState(false);

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

  // On mount: fetch health + initial tasks + pages; open WS; fetch stats + positions
  useEffect(() => {
    let alive = true;

    (async () => {
      try {
        const h = await api.health();
        if (alive) conn.setHealth(h);
      } catch (e) {
        console.warn("health fetch failed:", e);
      }
      try {
        const r = await api.listTasks({ limit: 100 });
        if (alive) useTasksStore.getState().setInitialTasks(r.tasks);
      } catch (e) {
        console.warn("initial tasks fetch failed:", e);
      }
      try {
        const p = await api.listWhopPages();
        if (alive) setPages(p.pages);
      } catch (e) {
        console.warn("initial pages fetch failed:", e);
      }
      refreshStats();
      refreshPositions();
    })();

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

  // Compute orphan count whenever tasks or pages change
  const pageUrls = useMemo(() => new Set(pages.map((p) => p.url)), [pages]);
  useEffect(() => {
    const orphans = tasks.filter(
      (t) => t.message?.url == null || !pageUrls.has(t.message.url),
    );
    setOrphanCount(orphans.length);
  }, [tasks, pageUrls, setOrphanCount]);

  if (pages.length === 0 && orphanCount === 0) {
    return <main className="main"><EmptyState /></main>;
  }

  const activePage =
    activeTabId === "orphan" || activeTabId === null
      ? null
      : pages.find((p) => p.id === activeTabId) ?? null;
  const filteredTasks =
    activeTabId === "orphan"
      ? selectTasksByUrl(tasks, null, pageUrls)
      : activePage
        ? selectTasksByUrl(tasks, activePage.url, pageUrls)
        : [];

  return (
    <main className="main">
      <section className="stream">
        <PageTabs />
        <PageInfoBar page={activePage} orphanCount={orphanCount} />
        <PageActionBar page={activePage} onOpenSettings={() => setSettingsOpen(true)} />
        {filteredTasks.length === 0 ? (
          <div className="empty-state"><p>该监听页暂无任务。</p></div>
        ) : (
          <TaskStream tasks={filteredTasks} pushEventsByTask={pushEventsByTask} expandMode={expandMode} />
        )}
      </section>
      <RightRail />
      {settingsOpen && activePage && (
        <PageSettingsModal page={activePage} onClose={() => setSettingsOpen(false)} />
      )}
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
