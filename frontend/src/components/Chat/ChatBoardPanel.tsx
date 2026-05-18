import { useEffect, useMemo } from "react";
import type { WhopPage } from "../../api/domain-types";
import { useChatStore } from "../../stores/chatStore";
import { groupIntoCards } from "./chatCards";
import { buildExportPayload, triggerJsonDownload } from "./chatExport";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { ChatMetaBar } from "./ChatMetaBar";
import "./ChatBoardPanel.css";

interface Props {
  page: WhopPage;
  week: string;                  // e.g., "2026-W21"
}

export function ChatBoardPanel({ page, week }: Props) {
  const cache = useChatStore((s) => s.caches[`${page.id}|${week}`]);
  const fetch = useChatStore((s) => s.fetch);

  const watchedSenders = page.settings.watched_senders ?? [];
  const maxN = page.settings.chat_card_max_msgs ?? 5;

  useEffect(() => {
    fetch(page.id, week, watchedSenders);
    // Intentionally NOT depending on watchedSenders — backend returns all
    // authors for the week regardless; filtering is client-side via
    // groupIntoCards. Refetching on watch changes would just reload identical data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page.id, week, fetch]);

  const messages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];

  const cards = useMemo(
    () => groupIntoCards(messages, new Set(watchedSenders), maxN),
    [messages, watchedSenders, maxN],
  );

  function handleExport() {
    const payload = buildExportPayload({
      page_id: page.id,
      page_name: page.name ?? page.url,
      week: cache?.week ?? { start: "", end: "" },
      watched_senders: watchedSenders,
      messages,
      cards,
    });
    triggerJsonDownload(`chat-${page.id}-${week}.json`, payload);
  }

  function handleSenderChange(next: string[]) {
    // After PATCH succeeds in ChatSenderBar, refetch is unnecessary —
    // the server already returned all authors for the week. Card grouping
    // is purely client-side, so just trust the optimistic update.
    // (No-op here intentionally; the store update will happen via the
    // PageSettingsModal / PATCH flow if persistence matters for refresh.)
    void next;
  }

  return (
    <div className="chat-panel">
      <ChatMetaBar
        messageCount={messages.length}
        watchedCount={watchedSenders.length}
        onExport={handleExport}
      />
      <ChatSenderBar
        pageId={page.id}
        authors={authors}
        watchedSenders={watchedSenders}
        onChange={handleSenderChange}
      />
      <div className="chat-board">
        {cards.length === 0
          ? <div className="chat-empty">本周无聊天消息 · 切换周或调整发送者过滤</div>
          : cards.map((c) => <ChatCard key={c.id} card={c} />)}
      </div>
    </div>
  );
}
