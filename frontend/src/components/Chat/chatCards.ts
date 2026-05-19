export interface QuotedRef {
  message_id: string | null;
  author: string;
  content: string;
  posted_at: string | null;
}

export interface ChatMessageOut {
  id: string;
  page_id: string;
  author: string;
  content: string;
  posted_at: string;
  quoted?: QuotedRef;
}

export type ChatCard =
  | {
      kind: "quote";
      id: string;           // = target.id
      target: ChatMessageOut;
      quoted: QuotedRef;
    }
  | {
      kind: "batch";
      id: string;           // = `batch:${msgs[0].id}`
      target_author: string;
      msgs: ChatMessageOut[];
    };

/** Max messages per batch card. When a watched sender posts a 9th
 *  consecutive non-quote message, we close the current batch and open
 *  a new one (same author) — no truncation, no "+N more". */
export const MAX_MSGS_PER_BATCH = 8;

export function groupIntoCards(
  messages: ChatMessageOut[],
  watchedSenders: Set<string>,
): ChatCard[] {
  const out: ChatCard[] = [];
  let currentBatch: Extract<ChatCard, { kind: "batch" }> | null = null;

  const isWatched = (author: string): boolean =>
    watchedSenders.size === 0 || watchedSenders.has(author);

  for (const m of messages) {
    if (!isWatched(m.author)) continue;   // skip; do not break currentBatch

    if (m.quoted) {
      if (currentBatch) {
        out.push(currentBatch);
        currentBatch = null;
      }
      out.push({
        kind: "quote",
        id: m.id,
        target: m,
        quoted: m.quoted,
      });
      continue;
    }

    const sameAuthorAndRoom =
      currentBatch !== null &&
      currentBatch.target_author === m.author &&
      currentBatch.msgs.length < MAX_MSGS_PER_BATCH;
    if (sameAuthorAndRoom) {
      currentBatch!.msgs.push(m);
    } else {
      if (currentBatch) out.push(currentBatch);
      currentBatch = {
        kind: "batch",
        id: `batch:${m.id}`,
        target_author: m.author,
        msgs: [m],
      };
    }
  }

  if (currentBatch) out.push(currentBatch);
  return out;
}
