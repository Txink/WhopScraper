import { useEffect, useMemo, useState } from "react";
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

  // Local state seeded from page settings; stays responsive to chip toggles
  // without waiting for parent re-fetch. Re-syncs if upstream settings change
  // (e.g., PageSettingsModal save).
  const [watchedSenders, setWatchedSenders] = useState<string[]>(
    page.settings.watched_senders ?? [],
  );
  useEffect(() => {
    setWatchedSenders(page.settings.watched_senders ?? []);
  }, [page.settings.watched_senders]);

  const maxN = page.settings.chat_card_max_msgs ?? 5;

  useEffect(() => {
    // Fetch full week's messages once per (page, week). Senders filter is
    // applied client-side via groupIntoCards — no need to re-fetch on toggle.
    fetch(page.id, week, []);
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
    setWatchedSenders(next);
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
