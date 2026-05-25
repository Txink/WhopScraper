import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { configureHttp, api, HttpError } from "./api/http";
import { configureRequest } from "./api/_request";
import { createWsClient } from "./api/ws";
import { handleOrderChanged, handleAlertChanged, handleAlertTriggered, handleTaskPushEvent } from "./api/wsHandlers";
import { useConnStore } from "./stores/conn";
import { useTasksStore, selectTasksByUrl } from "./stores/tasks";
import { useStatsStore } from "./stores/stats";
import { usePositionsStore } from "./stores/positions";
import { useQuotesStore } from "./stores/quotes";
import { useExecutionsStore } from "./stores/executions";
import type { Quote, Execution, WhopPage } from "./api/domain-types";
import { useViewStore } from "./stores/view";
import { usePageTabsStore } from "./stores/pageTabs";
import { useChildPagesStore } from "./stores/childPages";
import { TopBar } from "./components/TopBar";
import { PositionsPanel } from "./components/Positions/PositionsPanel";
import { Login } from "./components/Login";
import { PageInfoBar } from "./components/Dashboard/PageInfoBar";
import { PageActionBar } from "./components/Dashboard/PageActionBar";
import { PageSettingsModal } from "./components/Dashboard/PageSettingsModal";
import { WeekPaginator } from "./components/Dashboard/WeekPaginator";
import { computeWeeks, weekKeyOf, monthOf, todayInShanghai } from "./components/Dashboard/weekUtils";
import { ChatBoardPanel } from "./components/Chat/ChatBoardPanel";
import { groupIntoCards } from "./components/Chat/chatCards";
import { buildExportPayload, triggerJsonDownload } from "./components/Chat/chatExport";
import { useChatStore } from "./stores/chatStore";
import { DatabaseRecordsPanel } from "./components/Dashboard/DatabaseRecordsPanel";
import { EmptyState } from "./components/Dashboard/EmptyState";
import { LongportSettingsModal } from "./components/Dashboard/LongportSettingsModal";
import { SimPanel } from "./components/Sim/SimPanel";
import { AlertToastStack } from "./components/AlertNotifications/AlertToastStack";
import { NoticeStack } from "./components/Notice/NoticeStack";
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
  const tasks = useTasksStore((s) => s.tasks);
  const applyWs = useTasksStore((s) => s.applyWsEvent);

  const pages = usePageTabsStore((s) => s.pages);
  const setPages = usePageTabsStore((s) => s.setPages);
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

  // Debounce timer for execution-driven positions refetch. A successful
  // order can produce a burst of partial-fill execution.update pushes
  // before the order goes fully filled; coalescing them into one
  // /api/positions call avoids hammering the endpoint while still
  // giving the UI an up-to-date qty / avg_cost / P&L within ~600ms of
  // the last fill in the burst.
  const positionsRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
          useConnStore.getState().setRuntimeSettings(lp);
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
          const payload = evt.payload as { action: string; page?: WhopPage };
          if (payload.page) {
            if (payload.page.parent_chat_id != null) {
              // Sub-monitor: route into childPagesStore, ensure it doesn't show
              // up in top-level tabs.
              useChildPagesStore.getState().upsert(payload.page);
              usePageTabsStore.getState().removePageIfPresent(payload.page.id);
            } else {
              // Top-level: ensure childPagesStore drops it (in case it was a sub
              // that got promoted by a parent removal cascade), then forward to
              // the page-tabs store as today.
              useChildPagesStore.getState().remove(payload.page.id);
              usePageTabsStore.getState().applyPageChanged(evt);
            }
          } else {
            // No page payload — delegate to the existing handler unchanged.
            usePageTabsStore.getState().applyPageChanged(evt);
          }
        } else if (evt.type === "quote.snapshot") {
          // Streaming broker quote — overlay into quotesStore so the
          // PositionCard's last_done updates in real time. payload shape:
          // ``{ symbol: string, quote: QuoteOut-ish }``.
          const payload = evt.payload as { symbol?: string; quote?: Quote };
          if (payload?.symbol && payload.quote) {
            useQuotesStore.getState().upsertQuote(payload.symbol, payload.quote);
          }
        } else if (evt.type === "execution.update") {
          // Streaming fill — upsert into executionsStore by order_id so
          // PositionCard's Day P/L stays current without polling
          // /api/broker/today_executions. payload mirrors ExecutionOut.
          const p = evt.payload as Execution;
          if (p?.order_id) {
            useExecutionsStore.getState().upsertExecution(p);
            // A fill changes the underlying position (qty, avg_cost,
            // market value). Schedule a debounced positions refetch so
            // bursts of partial fills coalesce into a single call.
            if (positionsRefreshTimerRef.current != null) {
              clearTimeout(positionsRefreshTimerRef.current);
            }
            positionsRefreshTimerRef.current = setTimeout(() => {
              positionsRefreshTimerRef.current = null;
              refreshPositions();
            }, 600);
          }
        } else if (evt.type === "chat.message_stored") {
          // WS payload is ``{page_id, message_id}`` only — we don't have the
          // posted_at, so we can't route the update by day. Assume the event
          // is for "now" (the scraper publishes events as messages arrive,
          // see backend/app/whop/chat_writer.py), and refresh only the
          // current Beijing-day slice + current-month counts for that page,
          // if either is already cached. Fire-and-forget.
          const p = evt.payload as { page_id?: string; message_id?: number };
          if (p?.page_id) {
            const today = todayInShanghai();
            const month = monthOf(today);
            const store = useChatStore.getState();
            if (store.caches[`${p.page_id}|${today}`]) {
              void store.fetchDay(p.page_id, today, []);
            }
            if (store.counts[`${p.page_id}|${month}`]) {
              void store.fetchCounts(p.page_id, month);
            }
          }
        } else if (evt.type === "order.changed") {
          handleOrderChanged(evt);
        } else if (evt.type === "alert.changed") {
          handleAlertChanged(evt);
        } else if (evt.type === "alert.triggered") {
          handleAlertTriggered(evt);
        } else {
          applyWs(evt);
          // task.push_event is broadcast as the catch-all task store
          // applies it (status, push history). Also mirror into the
          // orders store so the trading panel reflects broker status.
          if (evt.type === "task.push_event") handleTaskPushEvent(evt);
        }
        useConnStore.getState().setLastEventId(evt.event_id);
      },
      onStatus: (s) => useConnStore.getState().setWs(s),
    });
    client.connect();

    return () => {
      alive = false;
      client.disconnect();
      if (positionsRefreshTimerRef.current != null) {
        clearTimeout(positionsRefreshTimerRef.current);
        positionsRefreshTimerRef.current = null;
      }
    };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Dashboard now shows exactly one chat-source page (the first one the
  // backend returns). Top-level stock/option pages still exist in storage
  // but are managed via the chat page's settings modal (正股/期权 tabs).
  const childPagesMap = useChildPagesStore((s) => s.byParent);
  const pageUrls = useMemo(() => new Set(pages.map((p) => p.url)), [pages]);
  const activePage = useMemo(
    () => pages.find((p) => p.source === "chat") ?? null,
    [pages],
  );
  const filteredTasks = activePage
    ? selectTasksByUrl(tasks, activePage.url, pageUrls)
    : [];
  // Silence unused-var warnings while keeping childPagesStore subscribed —
  // its updates still need to trigger Dashboard re-renders so the chat
  // panel's attached-monitor lists stay fresh.
  void childPagesMap;

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

  if (pagesLoaded && !activePage) {
    return <EmptyState />;
  }

  // Returns ONLY the left-zone content (children of <section
  // className="stream">) — the .main shell and PositionsPanel are
  // owned by ContentRouter so they survive view switches without
  // remounting (would otherwise destroy the chart, reset trade list
  // scroll, re-subscribe quotes, etc.).
  return (
    <>
      <div className="page-meta-row">
        <div className="page-meta-stack">
          <PageInfoBar
            page={activePage}
            newMessageCount={newMessageCount}
            onJumpToCurrent={() => setCurrentWeekKey(realCurrentWeekKey)}
          />
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
          onOpenSettings={() => setSettingsOpen(true)}
          onExport={
            activePage
              ? () => {
                  const day = todayInShanghai();
                  const cache = useChatStore.getState().caches[`${activePage.id}|${day}`];
                  const messages = cache?.messages ?? [];
                  const watched = activePage.settings.watched_senders ?? [];
                  const cards = groupIntoCards(messages, new Set(watched));
                  const payload = buildExportPayload({
                    page_id: activePage.id,
                    page_name: activePage.name ?? activePage.url,
                    day: cache?.day ?? { start: "", end: "" },
                    watched_senders: watched,
                    messages,
                    cards,
                  });
                  triggerJsonDownload(`chat-${activePage.id}-${day}.json`, payload);
                }
              : undefined
          }
        />
      </div>
      {activePage && <ChatBoardPanel page={activePage} />}
      {/* PageSettingsModal is viewport-level (position:fixed); rendering
          it inside .stream is purely structural — it visually anchors to
          the viewport regardless. */}
      {settingsOpen && activePage && (
        <PageSettingsModal page={activePage} onClose={() => setSettingsOpen(false)} />
      )}
    </>
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

  return <DatabaseRecordsPanel pageNameByUrl={pageNameByUrl} />;
}

function ContentRouter({ token }: { token: string }) {
  // The .main shell and <PositionsPanel/> are rendered ONCE here so the
  // right zone keeps its React identity (and thus all internal state:
  // selected symbol's detail pane, chart canvas, trade list scroll,
  // quote subscriptions) when the user switches the left view between
  // dashboard / database. Only the .stream child swaps.
  const view = useViewStore((s) => s.view);
  let leftContent: ReactNode;
  if (view === "database") leftContent = <DatabaseView />;
  else leftContent = <Dashboard token={token} />;

  return (
    <main className="main">
      <section className="stream">{leftContent}</section>
      <PositionsPanel />
    </main>
  );
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
    configureRequest({ baseUrl: BASE_URL, token: stored });
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
            useConnStore.getState().setRuntimeSettings(saved);
          }}
        />
      )}
      <SimPanel open={simPanelOpen} onClose={() => setSimPanelOpen(false)} />
      <AlertToastStack />
      <NoticeStack anchor="page" />
    </div>
  );
}
