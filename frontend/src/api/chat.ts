import type { ChatMessageOut } from "../components/Chat/chatCards";

/** GET /api/whop/pages/{page_id}/chat-messages — single Beijing-day window. */
export interface ChatMessagesResponse {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  day: { start: string; end: string };
}

/** GET /api/whop/pages/{page_id}/chat-message-counts — per-day counts for
 *  one Beijing calendar month. Days with zero messages are omitted. */
export interface ChatMessageCountsResponse {
  month: string;
  counts: Record<string, number>;
}

/** Auth is via ``?token=`` query param on every request — same surface
 *  as the WS handshake, kept in sync with {@link configureHttp} in
 *  ``api/http.ts``. We don't import the http module here to avoid the
 *  cross-import + share its singleton, so we read the token from the
 *  same ``localStorage`` slot ``App.tsx`` populates. */
function authedUrl(path: string, params?: Record<string, string>): string {
  const base =
    (import.meta.env.VITE_API_BASE as string | undefined) ??
    window.location.origin;
  const url = new URL(path, base);
  if (params) {
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  }
  const token = localStorage.getItem("APP_TOKEN") ?? "";
  if (token) url.searchParams.set("token", token);
  return url.toString();
}

export async function listChatMessagesForDay(
  pageId: string,
  day: string,
  senders: string[],
): Promise<ChatMessagesResponse> {
  const params: Record<string, string> = { day };
  if (senders.length) params.senders = senders.join(",");
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/chat-messages`,
    params,
  );
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`listChatMessagesForDay ${pageId} ${day}: ${resp.status}`);
  }
  return resp.json();
}

export async function listChatMessageCounts(
  pageId: string,
  month: string,
): Promise<ChatMessageCountsResponse> {
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/chat-message-counts`,
    { month },
  );
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`listChatMessageCounts ${pageId} ${month}: ${resp.status}`);
  }
  return resp.json();
}

export async function patchWatchedSenders(
  pageId: string,
  watchedSenders: string[],
): Promise<void> {
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/settings`,
  );
  const resp = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ watched_senders: watchedSenders }),
  });
  if (!resp.ok) {
    throw new Error(`patchWatchedSenders ${pageId}: ${resp.status}`);
  }
}

