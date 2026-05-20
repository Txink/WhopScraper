import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { WhopPage } from "../../api/domain-types";
import { api } from "../../api/http";
import { useChatStore } from "../../stores/chatStore";
import { useChildPagesStore } from "../../stores/childPages";
import { useTasksStore } from "../../stores/tasks";
import { useConnStore } from "../../stores/conn";
import { isoWeekBounds } from "../Dashboard/weekUtils";
import { groupIntoCards } from "./chatCards";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { buildTimeline, buildFilterBlocks, buildStreamGroups } from "./chatTimeline";
import { StockCard } from "./StockCard";
import { OptionCard } from "./OptionCard";
import { StreamView } from "./StreamView";
import "./ChatBoardPanel.css";

interface Props {
  page: WhopPage;
  week: string;                  // e.g., "2026-W21"
}

export type SenderMode = "filter" | "highlight";

const EMPTY_PAGES: WhopPage[] = [];

const modeStorageKey = (pageId: string): string => `chat-sender-mode-${pageId}`;

function loadMode(pageId: string): SenderMode {
  try {
    const v = localStorage.getItem(modeStorageKey(pageId));
    return v === "highlight" ? "highlight" : "filter";
  } catch { return "filter"; }
}

function persistMode(pageId: string, mode: SenderMode): void {
  try { localStorage.setItem(modeStorageKey(pageId), mode); } catch { /* noop */ }
}

export function ChatBoardPanel({ page, week }: Props) {
  const cache = useChatStore((s) => s.caches[`${page.id}|${week}`]);
  const fetch = useChatStore((s) => s.fetch);

  // Local state seeded from page settings; stays responsive to chip toggles
  // without waiting for parent re-fetch. Re-syncs if upstream settings change
  // (e.g., PageSettingsModal save).
  const [watchedSenders, setWatchedSenders] = useState<string[]>(
    page.settings.watched_senders ?? [],
  );
  useEffect(() => {
    setWatchedSenders(page.settings.watched_senders ?? []);
  }, [page.settings.watched_senders]);

  // Filter vs highlight is a UI-only preference — persisted to
  // localStorage per page so it survives reloads without backend churn.
  const [mode, setMode] = useState<SenderMode>(() => loadMode(page.id));
  useEffect(() => { setMode(loadMode(page.id)); }, [page.id]);
  function handleModeChange(next: SenderMode) {
    setMode(next);
    persistMode(page.id, next);
  }

  useEffect(() => {
    // Fetch full week's messages once per (page, week). Senders filter is
    // applied client-side via groupIntoCards — no need to re-fetch on toggle.
    fetch(page.id, week, []);
  }, [page.id, week, fetch]);

  // ── Child monitor pages + their tasks ────────────────────────────────
  const children = useChildPagesStore((s) => s.byParent[page.id] ?? EMPTY_PAGES);
  const childUrls = useMemo(() => children.map((c) => c.url), [children]);
  const urlToMonitorName = useMemo(
    () => Object.fromEntries(children.map((c) => [c.url, c.name])),
    [children],
  );

  const allTasks = useTasksStore((s) => s.tasks);
  const pushEventsByTask = useTasksStore((s) => s.pushEventsByTask);
  const autoTrade = useConnStore((s) => s.autoTrade);

  const childTasks = useMemo(
    () =>
      allTasks.filter(
        (t) => t.message.url != null && childUrls.includes(t.message.url),
      ),
    [allTasks, childUrls],
  );

  // Fetch children + their tasks on mount / page / week change.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.listWhopPages({ parentChatId: page.id });
        if (!alive) return;
        useChildPagesStore.getState().setByParent(page.id, r.pages);

        const urls = r.pages.map((p) => p.url);
        if (urls.length === 0) return;
        const { start, end } = isoWeekBounds(week);
        const tr = await api.listTasks({
          urls,
          week_start: start,
          week_end: end,
          limit: 500,
        });
        if (!alive) return;
        for (const t of tr.tasks) useTasksStore.getState().upsertTask(t);
      } catch (e) {
        console.warn("chat children fetch failed:", e);
      }
    })();
    return () => { alive = false; };
  }, [page.id, week]);

  // Single-accordion for signal cards across the whole board.
  const [expandedSignalId, setExpandedSignalId] = useState<string | null>(null);
  useEffect(() => {
    setExpandedSignalId(null);
  }, [page.id]);
  const toggleSignal = useCallback((taskId: string) => {
    setExpandedSignalId((curr) => (curr === taskId ? null : taskId));
  }, []);

  // ── Data ─────────────────────────────────────────────────────────────
  const messages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];

  /** name → "stock" | "option" for children whose source is known. */
  const monitorSources = useMemo<Record<string, "stock" | "option">>(
    () =>
      Object.fromEntries(
        children
          .filter((c) => c.source === "stock" || c.source === "option")
          .map((c) => [c.name, c.source as "stock" | "option"]),
      ),
    [children],
  );

  /** authors from chat messages merged with child monitor pages.
   *  Monitor names are included even when count=0 so users can toggle
   *  them on before any signal arrives this week. */
  const authorsWithMonitors = useMemo(() => {
    const seen = new Set<string>();
    const out: { name: string; count: number }[] = [];
    for (const a of authors) {
      out.push(a);
      seen.add(a.name);
    }
    for (const c of children) {
      if (seen.has(c.name)) continue;
      const count = childTasks.filter((t) => t.message.url === c.url).length;
      out.push({ name: c.name, count });
    }
    return out;
  }, [authors, children, childTasks]);

  const watchedSet = useMemo(() => new Set(watchedSenders), [watchedSenders]);

  // Merged chronological timeline of chat messages + child tasks.
  const timeline = useMemo(
    () => buildTimeline(messages, childTasks, urlToMonitorName),
    [messages, childTasks, urlToMonitorName],
  );

  function handleSenderChange(next: string[]) {
    setWatchedSenders(next);
  }

  // ── Sticky-bottom scroll ──────────────────────────────────────────────
  const boardRef = useRef<HTMLDivElement | null>(null);
  const wasAtBottomRef = useRef(true);

  useLayoutEffect(() => {
    const el = boardRef.current;
    if (!el || !wasAtBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  const hasWatched = watchedSenders.length > 0;
  useLayoutEffect(() => {
    const el = boardRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    wasAtBottomRef.current = true;
  }, [mode, hasWatched]);

  function handleBoardScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    wasAtBottomRef.current = distFromBottom < 120;
  }

  // ── Routing ───────────────────────────────────────────────────────────
  //   no timeline items → empty state
  //   filter mode + watched senders → buildFilterBlocks → chat/aggregate cards
  //   highlight mode (or no watched) → buildStreamGroups → StreamView
  let body: React.ReactNode;

  if (timeline.length === 0) {
    body = (
      <div className="chat-empty">本周无消息 · 切换周或调整发送者过滤</div>
    );
  } else if (mode === "filter" && watchedSenders.length > 0) {
    // Chat side: groupIntoCards consumes the FULL message list so its
    // MAX_CONTEXT_PER_BATCH=5 buffer/gap logic can split a watched run
    // into a new big card whenever 5+ non-watched messages intervene.
    // Aggregate stock/option blocks come from buildFilterBlocks.
    const chatCards = groupIntoCards(messages, watchedSet);
    const aggBlocks = buildFilterBlocks(timeline, watchedSet, urlToMonitorName);
    body = (
      <>
        {chatCards.map((c) => (
          <ChatCard key={c.id} card={c} />
        ))}
        {aggBlocks.map((b, i) => {
          const isStock = b.kind === "aggregate-stock";
          const sourceCls = isStock ? "stock" : "option";
          const titleZh = isStock ? "正股信号" : "期权信号";
          return (
            <div key={`agg-${b.kind}-${i}`} className={`chat-card aggregate ${sourceCls}`}>
              <div className="chat-card-head">
                <span
                  className="avatar-lg"
                  style={{
                    background: isStock
                      ? "var(--source-stock)"
                      : "var(--source-option)",
                  }}
                >
                  ∑
                </span>
                <span className="sender-name">{titleZh}</span>
                <span className="meta">
                  <span className="msg-count">{b.tasks.length} signals</span>
                  <span>{b.monitorNames.join(" + ")}</span>
                </span>
              </div>
              <div className="chat-thread">
                {b.tasks.map((t) => {
                  const Card = t.type === "option" ? OptionCard : StockCard;
                  const monitorName =
                    urlToMonitorName[t.message.url ?? ""] ?? "(unknown)";
                  return (
                    <Card
                      key={t.id}
                      monitorName={monitorName}
                      task={t}
                      pushEvents={pushEventsByTask[t.id] ?? []}
                      expanded={expandedSignalId === t.id}
                      onToggle={() => toggleSignal(t.id)}
                      autoTrade={autoTrade}
                      align="left"
                    />
                  );
                })}
              </div>
            </div>
          );
        })}
      </>
    );
  } else {
    // Highlight mode or no watched senders → stream view.
    // All routes go through StreamView, which internally renders ChatMessage
    // for chat-msg groups and StockCard/OptionCard for signal groups.
    const groups = buildStreamGroups(timeline, urlToMonitorName);
    body = (
      <StreamView
        groups={groups}
        watched={watchedSet}
        pushEventsByTask={pushEventsByTask}
        expandedTaskId={expandedSignalId}
        onToggleTask={toggleSignal}
        autoTrade={autoTrade}
      />
    );
  }

  return (
    <div className="chat-panel">
      <ChatSenderBar
        pageId={page.id}
        authors={authorsWithMonitors}
        watchedSenders={watchedSenders}
        onChange={handleSenderChange}
        mode={mode}
        onModeChange={handleModeChange}
        monitorSources={monitorSources}
      />
      <div className="chat-board" ref={boardRef} onScroll={handleBoardScroll}>
        {body}
      </div>
    </div>
  );
}
