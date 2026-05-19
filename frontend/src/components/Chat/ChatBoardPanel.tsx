import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { WhopPage } from "../../api/domain-types";
import { useChatStore } from "../../stores/chatStore";
import { groupIntoCards } from "./chatCards";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { GroupChatView } from "./GroupChatView";
import "./ChatBoardPanel.css";

interface Props {
  page: WhopPage;
  week: string;                  // e.g., "2026-W21"
}

export type SenderMode = "filter" | "highlight";

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

  const messages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];

  const cards = useMemo(
    () => groupIntoCards(messages, new Set(watchedSenders)),
    [messages, watchedSenders],
  );

  function handleSenderChange(next: string[]) {
    setWatchedSenders(next);
  }

  // Sticky-bottom scroll. ref starts true so the first paint (and week
  // switches that re-populate the list) anchors at the bottom. After
  // that, scroll events update the flag — if the user scrolls up to
  // read history, new messages no longer yank the view back down.
  // useLayoutEffect avoids a one-frame flicker where the list briefly
  // shows at top before scrolling.
  const boardRef = useRef<HTMLDivElement | null>(null);
  const wasAtBottomRef = useRef(true);

  // New messages: snap to bottom ONLY when user was already there. Never
  // yank up a user who scrolled to read history.
  useLayoutEffect(() => {
    const el = boardRef.current;
    if (!el || !wasAtBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  // View-shape transitions (mode toggle, first watched added or last
  // watched removed): the layout flips between cards / group view /
  // empty so dramatically that preserving the old scrollTop drops the
  // user at a meaningless middle position. Force re-anchor and reset
  // the ref — subsequent new messages will follow automatically.
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

  // Routing:
  //   no msgs → empty state
  //   no watched → group view (mode is moot — nothing to filter/highlight)
  //   filter mode → batch/quote cards for watched only
  //   highlight mode → group view with watched senders' avatar tinted
  let body: React.ReactNode;
  if (messages.length === 0) {
    body = (
      <div className="chat-empty">本周无聊天消息 · 切换周或调整发送者过滤</div>
    );
  } else if (watchedSenders.length === 0) {
    body = <GroupChatView messages={messages} />;
  } else if (mode === "filter") {
    body = cards.map((c) => <ChatCard key={c.id} card={c} />);
  } else {
    body = <GroupChatView messages={messages} watched={new Set(watchedSenders)} />;
  }

  return (
    <div className="chat-panel">
      <ChatSenderBar
        pageId={page.id}
        authors={authors}
        watchedSenders={watchedSenders}
        onChange={handleSenderChange}
        mode={mode}
        onModeChange={handleModeChange}
      />
      <div className="chat-board" ref={boardRef} onScroll={handleBoardScroll}>
        {body}
      </div>
    </div>
  );
}
