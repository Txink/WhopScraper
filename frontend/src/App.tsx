import { useEffect, useMemo, useRef, useState } from "react";
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
import { PageWhitelistBar } from "./components/Dashboard/PageWhitelistBar";
import { PageActionBar } from "./components/Dashboard/PageActionBar";
import { PageSettingsModal } from "./components/Dashboard/PageSettingsModal";
import { TaskStream } from "./components/Dashboard/TaskStream";
import { WeekPaginator } from "./components/Dashboard/WeekPaginator";
import { computeWeeks, weekKeyOf } from "./components/Dashboard/weekUtils";
import { OrphanCleanupBar } from "./components/Dashboard/OrphanCleanupBar";
import { DatabaseRecordsPanel } from "./components/Dashboard/DatabaseRecordsPanel";
import { EmptyState } from "./components/Dashboard/EmptyState";
import { LongportSettingsModal } from "./components/Dashboard/LongportSettingsModal";
import { SimPanel } from "./components/Sim/SimPanel";
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

function Dashboard({ token }: { token: string }) {
  useStickyTop();
  const conn = useConnStore();
  const autoTrade = useConnStore((s) => s.autoTrade);
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
  const pagesLoaded = usePageTabsStore((s) => s.pagesLoaded);

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
        const lp = await api.getLongportSettings();
        if (alive) {
          useConnStore.getState().setRuntimeSettings({
            mode: lp.mode,
            dry_run: lp.dry_run,
            auto_trade: lp.auto_trade,
          });
        }
      } catch (e) {
        console.warn("longport settings fetch failed:", e);
      }
      try {
        const status = await api.getBrokerStatus();
        if (alive) {
          useConnStore.getState().setBrokerStatus({
            is_real: status.is_real,
            last_init_error: status.last_init_error ?? null,
          });
        }
      } catch (e) {
        console.warn("broker status fetch failed:", e);
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

  // Compute orphan count whenever tasks or pages change.
  // Gate on pagesLoaded so we don't recompute orphans against a stale/empty
  // page list during the first remount paint (which would falsely flag every
  // task as orphan and trigger the orphan auto-select effect below).
  const pageUrls = useMemo(() => new Set(pages.map((p) => p.url)), [pages]);
  useEffect(() => {
    if (!pagesLoaded) return;
    const orphans = tasks.filter(
      (t) => t.message?.url == null || !pageUrls.has(t.message.url),
    );
    setOrphanCount(orphans.length);
  }, [tasks, pageUrls, setOrphanCount, pagesLoaded]);

  // Auto-select orphan tab when no pages exist but orphans do (so user isn't stuck)
  useEffect(() => {
    if (!pagesLoaded) return;
    if (pages.length === 0 && orphanCount > 0 && activeTabId !== "orphan") {
      usePageTabsStore.getState().setActiveTab("orphan");
    }
  }, [pages.length, orphanCount, activeTabId, pagesLoaded]);

  const isOrphanTab = activeTabId === "orphan";
  const activePage =
    isOrphanTab || activeTabId === null
      ? null
      : pages.find((p) => p.id === activeTabId) ?? null;
  const filteredTasks =
    isOrphanTab
      ? selectTasksByUrl(tasks, null, pageUrls)
      : activePage
        ? selectTasksByUrl(tasks, activePage.url, pageUrls)
        : [];

  const { groups, weeks } = useMemo(() => computeWeeks(filteredTasks), [filteredTasks]);
  const [currentWeekKey, setCurrentWeekKey] = useState<string | null>(null);

  useEffect(() => {
    if (weeks.length === 0) {
      if (currentWeekKey !== null) setCurrentWeekKey(null);
      return;
    }
    if (currentWeekKey == null || !groups.has(currentWeekKey)) {
      setCurrentWeekKey(weeks[0].key);
    }
  }, [weeks, groups, currentWeekKey]);

  // Captured at mount; a session that crosses midnight Sunday will not refresh
  // this. Acceptable per spec — sessions rarely live that long, and TaskStream
  // remounts on Dashboard remount.
  const realCurrentWeekKey = useMemo(() => weekKeyOf(new Date().toISOString()), []);
  const onPastWeek = currentWeekKey !== null && currentWeekKey !== realCurrentWeekKey;
  const realCurrentCount = groups.get(realCurrentWeekKey)?.length ?? 0;
  // Baseline: count of tasks in the real-current week last time the user was
  // viewing it. While on a past week the baseline is frozen, so newMessageCount
  // reflects only tasks that arrived AFTER the user navigated away.
  const seenCurrentRef = useRef<number>(realCurrentCount);
  useEffect(() => {
    if (!onPastWeek) seenCurrentRef.current = realCurrentCount;
  }, [onPastWeek, realCurrentCount]);
  const newMessageCount =
    onPastWeek ? Math.max(0, realCurrentCount - seenCurrentRef.current) : 0;

  if (pages.length === 0 && orphanCount === 0) {
    return <main className="main"><EmptyState /></main>;
  }

  return (
    <main className="main">
      <section className="stream">
        <PageTabs />
        <div className="page-meta-row">
          <div className="page-meta-stack">
            <PageInfoBar
              page={activePage}
              orphanCount={orphanCount}
              mode={isOrphanTab ? "orphan" : "page"}
              newMessageCount={isOrphanTab ? 0 : newMessageCount}
              onJumpToCurrent={() => setCurrentWeekKey(realCurrentWeekKey)}
            />
            {!isOrphanTab && activePage && activePage.source === "stock" && (
              <PageWhitelistBar page={activePage} />
            )}
          </div>
          {weeks.length > 0 && currentWeekKey && (
            <WeekPaginator
              weeks={weeks}
              currentWeekKey={currentWeekKey}
              onSelect={setCurrentWeekKey}
            />
          )}
          <PageActionBar
            page={activePage}
            mode={isOrphanTab ? "orphan" : "page"}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        </div>
        {isOrphanTab && <OrphanCleanupBar orphanTasks={filteredTasks} />}
        {filteredTasks.length === 0 ? (
          <div className="empty-state"><p>该监听页暂无任务。</p></div>
        ) : (
          <TaskStream
            pushEventsByTask={pushEventsByTask}
            expandMode={expandMode}
            autoTrade={autoTrade}
            groups={groups}
            currentWeekKey={currentWeekKey}
          />
        )}
      </section>
      <RightRail />
      {settingsOpen && activePage && (
        <PageSettingsModal page={activePage} onClose={() => setSettingsOpen(false)} />
      )}
    </main>
  );
}

function DatabaseView() {
  const [pageNameByUrl, setPageNameByUrl] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    let alive = true;
    api
      .listWhopPages()
      .then((r) => {
        if (!alive) return;
        setPageNameByUrl(new Map(r.pages.map((p) => [p.url, p.name])));
      })
      .catch(() => {
        if (!alive) return;
        setPageNameByUrl(new Map());
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <main className="main">
      <section className="stream">
        <DatabaseRecordsPanel pageNameByUrl={pageNameByUrl} />
      </section>
      <RightRail />
    </main>
  );
}

function ContentRouter({ token }: { token: string }) {
  const view = useViewStore((s) => s.view);
  if (view === "whop") return <WhopPanel />;
  if (view === "database") return <DatabaseView />;
  return <Dashboard token={token} />;
}

export default function App() {
  const [longportSettingsOpen, setLongportSettingsOpen] = useState(false);
  const [simPanelOpen, setSimPanelOpen] = useState(false);
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
        connLongport={conn.longport}
        brokerIsReal={conn.brokerIsReal}
        brokerInitError={conn.brokerInitError}
        mode={conn.mode}
        dryRun={conn.dryRun}
        autoTrade={conn.autoTrade}
        onOpenLongportSettings={() => setLongportSettingsOpen(true)}
        onOpenSimulator={() => setSimPanelOpen(true)}
        onReloadBroker={async () => {
          try {
            const status = await api.reloadBroker();
            useConnStore.getState().setBrokerStatus({
              is_real: status.is_real,
              last_init_error: status.last_init_error ?? null,
            });
          } catch (e) {
            console.warn("broker reload failed:", e);
          }
        }}
        onLogout={handleLogout}
      />
      <ContentRouter token={token} />
      {longportSettingsOpen && (
        <LongportSettingsModal
          onClose={() => setLongportSettingsOpen(false)}
          onSaved={(saved) => {
            useConnStore.getState().setRuntimeSettings({
              mode: saved.mode,
              dry_run: saved.dry_run,
              auto_trade: saved.auto_trade,
            });
          }}
        />
      )}
      <SimPanel open={simPanelOpen} onClose={() => setSimPanelOpen(false)} />
    </div>
  );
}
