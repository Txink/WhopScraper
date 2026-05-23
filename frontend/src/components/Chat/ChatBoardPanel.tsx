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
  addDays,
  dayKeyOf,
  isoWeekBounds,
  isoWeekOfDay,
  monthOf,
  todayInShanghai,
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
  // 选中的北京日历日，决定渲染哪一天的消息以及 chatStore 拉取哪一天。
  const [selectedDate, setSelectedDate] = useState<string>(todayInShanghai());
  // Reset to today whenever the active page changes.
  useEffect(() => { setSelectedDate(todayInShanghai()); }, [page.id]);

  const today = todayInShanghai();
  const selectedWeek = useMemo(() => isoWeekOfDay(selectedDate), [selectedDate]);

  const cache = useChatStore((s) => s.caches[`${page.id}|${selectedDate}`]);
  const allCaches = useChatStore((s) => s.caches);
  const allCounts = useChatStore((s) => s.counts);
  const fetchDay = useChatStore((s) => s.fetchDay);
  const fetchCounts = useChatStore((s) => s.fetchCounts);

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

  // 进入 page：并行拉「今天」+「昨天」+ 当月计数。
  useEffect(() => {
    const t = todayInShanghai();
    const y = addDays(t, -1);
    fetchDay(page.id, t, []);
    fetchDay(page.id, y, []);
    fetchCounts(page.id, monthOf(t));
  }, [page.id, fetchDay, fetchCounts]);

  // selectedDate 变化：缺缓存就拉那一天；跨月就拉那月 counts。
  // chatStore 内部 in-flight dedupe 保证今天的双触发只发一次。
  useEffect(() => {
    const dayKey = `${page.id}|${selectedDate}`;
    if (!allCaches[dayKey]) fetchDay(page.id, selectedDate, []);
    const m = monthOf(selectedDate);
    const monthKey = `${page.id}|${m}`;
    if (!allCounts[monthKey]) fetchCounts(page.id, m);
  }, [page.id, selectedDate, allCaches, allCounts, fetchDay, fetchCounts]);

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

  // Fetch children + their tasks. The task-list query uses the ISO week containing selectedDate; dep is the week, so navigating within the same week reuses the cached fetch.
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
  // 后端按北京日切片，cache 里的 messages 已经是当天的；不再做客户端过滤。
  const messages = cache?.messages ?? [];
  const dayFilteredChildTasks = useMemo(
    () =>
      childTasks.filter(
        (t) => dayKeyOf(t.message.posted_at) === selectedDate,
      ),
    [childTasks, selectedDate],
  );

  /** chip 列表「形状」基于本 page 下所有已缓存天的作者并集；优先把当天的
   *  作者排在最前，保持视觉上「今天看到的人」在前。 */
  const allAuthorsForPage = useMemo(() => {
    const order: string[] = [];
    const seen = new Set<string>();
    const prefix = `${page.id}|`;
    // 先放当天的
    const todayCache = allCaches[`${page.id}|${selectedDate}`];
    if (todayCache) {
      for (const a of todayCache.authors) {
        if (!seen.has(a.name)) { order.push(a.name); seen.add(a.name); }
      }
    }
    // 再补其它已缓存天的
    for (const key of Object.keys(allCaches)) {
      if (!key.startsWith(prefix)) continue;
      if (key === `${page.id}|${selectedDate}`) continue;
      for (const a of allCaches[key].authors) {
        if (!seen.has(a.name)) { order.push(a.name); seen.add(a.name); }
      }
    }
    return order;
  }, [allCaches, page.id, selectedDate]);

  /** 当天的作者计数（用于 chip 上的 badge）。 */
  const dayCountsByAuthor = useMemo(() => {
    const m = new Map<string, number>();
    for (const msg of messages) m.set(msg.author, (m.get(msg.author) ?? 0) + 1);
    return m;
  }, [messages]);

  const dayScopedAuthors = useMemo(
    () => allAuthorsForPage.map((name) => ({
      name, count: dayCountsByAuthor.get(name) ?? 0,
    })),
    [allAuthorsForPage, dayCountsByAuthor],
  );

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

  /** chip 列表「形状」来自当前 page 已缓存所有天的作者并集 + 监控子页，保持稳定不随选中日切换重排；count 按 selectedDate 当日重算。 */
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

  // 翻月时按需拉那月 counts。
  useEffect(() => {
    if (!calendarOpen) return;
    const k = `${page.id}|${calendarMonth}`;
    if (!allCounts[k]) fetchCounts(page.id, calendarMonth);
  }, [calendarOpen, calendarMonth, page.id, fetchCounts, allCounts]);

  const prefetching = useMemo(() => {
    if (!calendarOpen) return false;
    return !allCounts[`${page.id}|${calendarMonth}`];
  }, [calendarOpen, calendarMonth, page.id, allCounts]);

  const hasMessagesOnDay = useCallback(
    (d: string) => {
      const c = allCounts[`${page.id}|${monthOf(d)}`];
      return c ? (c.counts[d] ?? 0) > 0 : false;
    },
    [allCounts, page.id],
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
