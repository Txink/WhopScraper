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
  image_url?: string | null;
}

/** Ordered, kind-tagged entry inside a card. ``watched`` items render
 *  right-aligned (target sender's own messages); ``context`` items
 *  render left-aligned with sender label + small avatar — the
 *  conversational lead-in or the inline bridge across short
 *  non-watched gaps. Order is strictly chronological by posted_at. */
export type BatchItem =
  | { kind: "watched"; msg: ChatMessageOut }
  | { kind: "context"; msg: ChatMessageOut };

export type ChatCard =
  | {
      kind: "quote";
      id: string;           // = first watched (quoting) msg's id
      target_author: string;
      /** The message being replied to — rendered as the card's first
       *  (left-aligned) row, above the items list. */
      quoted: QuotedRef;
      items: BatchItem[];   // starts with the quoting watched msg
    }
  | {
      kind: "batch";
      id: string;           // = `batch:${firstWatched.id}`
      target_author: string;
      items: BatchItem[];
    };

/** Gap threshold (in non-watched messages) that separates two cards.
 *  Strictly fewer than this many non-watched messages between two
 *  same-author watched runs → the runs MERGE into one card and the
 *  gap messages render inline at their chronological position.
 *  A gap of this size or larger → SPLIT; the new card takes the last
 *  MAX_CONTEXT_PER_BATCH of the gap as its lead-in context.  */
export const MAX_CONTEXT_PER_BATCH = 5;

export function groupIntoCards(
  messages: ChatMessageOut[],
  watchedSenders: Set<string>,
): ChatCard[] {
  const out: ChatCard[] = [];
  // The single in-progress card. Both kinds ("quote" and "batch") are
  // extensible via the same gap-bridging rule, so we hold whichever is
  // open in one variable until it's flushed.
  let chunk: ChatCard | null = null;
  // Non-watched messages accumulated since the last watched event.
  // Drained on every watched event — either absorbed inline (gap < cap)
  // or trimmed to the last cap entries as the next card's lead-in.
  let buffer: ChatMessageOut[] = [];

  const isWatched = (author: string): boolean =>
    watchedSenders.size === 0 || watchedSenders.has(author);

  const flush = (): void => {
    if (chunk) { out.push(chunk); chunk = null; }
  };

  for (const m of messages) {
    if (!isWatched(m.author)) {
      buffer.push(m);
      continue;
    }

    // Short gap, same watched author → extend the current card by
    // absorbing the buffered non-watched messages inline and appending
    // this watched message. The rule applies to quotes too: a quoted
    // reply that immediately follows the same author's run stays in
    // the existing card — the quoted snippet renders inline inside
    // its own bubble via m.quoted, no new card needed.
    if (
      chunk !== null &&
      chunk.target_author === m.author &&
      buffer.length < MAX_CONTEXT_PER_BATCH
    ) {
      for (const b of buffer) chunk.items.push({ kind: "context", msg: b });
      chunk.items.push({ kind: "watched", msg: m });
      buffer = [];
      continue;
    }

    // Long gap OR author switch → close current chunk and open a fresh
    // card. Kind is "quote" if this opening message itself carries a
    // quoted ref (so exports / header badges can distinguish "reply-
    // initiated" cards), otherwise "batch". Lead-in is the last
    // MAX_CONTEXT_PER_BATCH non-watched messages before this run.
    flush();
    const lead = buffer.slice(-MAX_CONTEXT_PER_BATCH);
    const baseItems: BatchItem[] = [
      ...lead.map((c): BatchItem => ({ kind: "context", msg: c })),
      { kind: "watched", msg: m },
    ];
    chunk = m.quoted
      ? {
          kind: "quote",
          id: m.id,
          target_author: m.author,
          quoted: m.quoted,
          items: baseItems,
        }
      : {
          kind: "batch",
          id: `batch:${m.id}`,
          target_author: m.author,
          items: baseItems,
        };
    buffer = [];
  }

  flush();
  return out;
}

/** Count of target-author bubbles in a card — used for the header's
 *  count badge. Both batch and quote cards qualify; context items are
 *  intentionally not counted (they're "borrowed", not the watched
 *  sender's own activity). */
export function watchedCount(card: ChatCard): number {
  if (card.kind === "quote" || card.kind === "batch") {
    return card.items.reduce(
      (n, it) => n + (it.kind === "watched" ? 1 : 0),
      0,
    );
  }
  return 0;
}
