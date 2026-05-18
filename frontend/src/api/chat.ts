import type { ChatMessageOut } from "../components/Chat/chatCards";

/** GET /api/whop/pages/{page_id}/chat-messages response envelope.
 *  Mirrors backend ``ChatMessagesOut`` (schemas.py) until we regenerate
 *  ``components.schemas`` via ``npm run gen:types`` (T19). */
export interface ChatMessagesResponse {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  week: { start: string; end: string };
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

export async function listChatMessages(
  pageId: string,
  week: string | null,
  senders: string[],
): Promise<ChatMessagesResponse> {
  const params: Record<string, string> = {};
  if (week) params.week = week;
  if (senders.length) params.senders = senders.join(",");
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/chat-messages`,
    params,
  );
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`listChatMessages ${pageId}: ${resp.status}`);
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

export async function patchChatCardMaxMsgs(
  pageId: string,
  chatCardMaxMsgs: number,
): Promise<void> {
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/settings`,
  );
  const resp = await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chat_card_max_msgs: chatCardMaxMsgs }),
  });
  if (!resp.ok) {
    throw new Error(`patchChatCardMaxMsgs ${pageId}: ${resp.status}`);
  }
}
