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
import {
  dayKeyOf,
  isoWeekBounds,
  isoWeekOfDay,
  monthOf,
  todayInShanghai,
  weeksCoveringMonth,
} from "../Dashboard/weekUtils";
import { groupIntoCards } from "./chatCards";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { buildTimeline, buildFilterBlocks, buildStreamGroups } from "./chatTimeline";
import { StockCard } from "./StockCard";
import { OptionCard } from "./OptionCard";
import { StreamView } from "./StreamView";
import { DayPicker } from "./DayPicker";
import "./ChatBoardPanel.css";

interface Props {
  page: WhopPage;
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

export function ChatBoardPanel({ page }: Props) {
  // Currently-selected calendar day, drives both the visible-message
  // filter and the ISO-week that gets fetched into chatStore.
  const [selectedDate, setSelectedDate] = useState<string>(todayInShanghai());
  // Reset to today whenever the active page changes.
  useEffect(() => { setSelectedDate(todayInShanghai()); }, [page.id]);

  const selectedWeek = isoWeekOfDay(selectedDate);
  const today = todayInShanghai();

  const cache = useChatStore((s) => s.caches[`${page.id}|${selectedWeek}`]);
  const fetch = useChatStore((s) => s.fetch);
  const allCaches = useChatStore((s) => s.caches);

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
    // Fetch full week's messages once per (page, selectedWeek). Senders
    // and day filters are applied client-side — no need to re-fetch on
    // toggles within the same week.
    fetch(page.id, selectedWeek, []);
  }, [page.id, selectedWeek, fetch]);

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
        const { start, end } = isoWeekBounds(selectedWeek);
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
  }, [page.id, selectedWeek]);

  // Single-accordion for signal cards across the whole board.
  const [expandedSignalId, setExpandedSignalId] = useState<string | null>(null);
  useEffect(() => {
    setExpandedSignalId(null);
  }, [page.id]);
  const toggleSignal = useCallback((taskId: string) => {
    setExpandedSignalId((curr) => (curr === taskId ? null : taskId));
  }, []);

  // ── Data ─────────────────────────────────────────────────────────────
  const rawMessages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];

  // Day-filter both messages and child-task signals to selectedDate so
  // every downstream consumer (groupIntoCards, buildTimeline, ...)
  // sees only that day's content.
  const messages = useMemo(
    () => rawMessages.filter((m) => dayKeyOf(m.posted_at) === selectedDate),
    [rawMessages, selectedDate],
  );
  const dayFilteredChildTasks = useMemo(
    () =>
      childTasks.filter(
        (t) => dayKeyOf(t.message.posted_at) === selectedDate,
      ),
    [childTasks, selectedDate],
  );

  /** Author chip counts for the selected day. Preserves the chip list
   *  shape from the week-cache `authors` (so chips don't flicker when
   *  switching days) but replaces each count with the count from today.
   *  Authors not in the week cache but present in today's messages are
   *  appended at the end. */
  const dayScopedAuthors = useMemo(() => {
    const dayCounts = new Map<string, number>();
    for (const m of messages) {
      dayCounts.set(m.author, (dayCounts.get(m.author) ?? 0) + 1);
    }
    const seen = new Set<string>();
    const out: { name: string; count: number }[] = [];
    for (const a of authors) {
      out.push({ name: a.name, count: dayCounts.get(a.name) ?? 0 });
      seen.add(a.name);
    }
    for (const [name, count] of dayCounts) {
      if (!seen.has(name)) out.push({ name, count });
    }
    return out;
  }, [messages, authors]);

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

  /** Chip bar entries for ChatSenderBar. List shape is taken from the
   *  week (chat authors + monitor pages) so the bar stays stable when
   *  the selected day changes; counts are day-scoped so the badge on
   *  each chip matches the messages and signals actually visible. */
  const authorsWithMonitors = useMemo(() => {
    const seen = new Set<string>();
    const out: { name: string; count: number }[] = [];
    for (const a of dayScopedAuthors) {
      out.push(a);
      seen.add(a.name);
    }
    for (const c of children) {
      if (seen.has(c.name)) continue;
      const count = dayFilteredChildTasks.filter(
        (t) => t.message.url === c.url,
      ).length;
      out.push({ name: c.name, count });
    }
    return out;
  }, [dayScopedAuthors, children, dayFilteredChildTasks]);

  const watchedSet = useMemo(() => new Set(watchedSenders), [watchedSenders]);

  // Merged chronological timeline of chat messages + child tasks
  // (already filtered to selectedDate above).
  const timeline = useMemo(
    () => buildTimeline(messages, dayFilteredChildTasks, urlToMonitorName),
    [messages, dayFilteredChildTasks, urlToMonitorName],
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

  // ── Calendar prefetch (covers the visible month so dots are reliable) ─
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarMonth, setCalendarMonth] = useState<string>(monthOf(selectedDate));

  useEffect(() => {
    if (!calendarOpen) return;
    for (const w of weeksCoveringMonth(calendarMonth)) {
      const key = `${page.id}|${w}`;
      if (!allCaches[key]) fetch(page.id, w, []);
    }
  }, [calendarOpen, calendarMonth, page.id, fetch, allCaches]);

  const prefetching = useMemo(() => {
    if (!calendarOpen) return false;
    return weeksCoveringMonth(calendarMonth).some(
      (w) => !allCaches[`${page.id}|${w}`],
    );
  }, [calendarOpen, calendarMonth, page.id, allCaches]);

  const hasMessagesOnDay = useCallback(
    (dayKey: string) => {
      const week = isoWeekOfDay(dayKey);
      const c = allCaches[`${page.id}|${week}`];
      if (!c) return false;
      return c.messages.some((m) => dayKeyOf(m.posted_at) === dayKey);
    },
    [allCaches, page.id],
  );

  // ── Routing ───────────────────────────────────────────────────────────
  //   no timeline items → empty state
  //   filter mode + watched senders → buildFilterBlocks → chat/aggregate cards
  //   highlight mode (or no watched) → buildStreamGroups → StreamView
  let body: React.ReactNode;

  if (timeline.length === 0) {
    body = (
      <div className="chat-empty">这一天还没有消息</div>
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
      <DayPicker
        selectedDate={selectedDate}
        maxDate={today}
        hasMessagesOnDay={hasMessagesOnDay}
        prefetching={prefetching}
        onChange={setSelectedDate}
        onCalendarOpenChange={(open, month) => {
          setCalendarOpen(open);
          if (open) setCalendarMonth(month);
        }}
        onVisibleMonthChange={setCalendarMonth}
      />
    </div>
  );
}
