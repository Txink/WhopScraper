import type { ChatCard, ChatMessageOut, QuotedRef } from "./chatCards";

/** Input bundle for {@link buildExportPayload}. The caller is expected to
 *  pass the *already-filtered* watched message list plus the cards derived
 *  from it via {@link groupIntoCards}, so this module does no grouping
 *  work — it just stamps ``card_index`` onto each surviving message and
 *  emits the JSON-friendly envelope. */
export interface ExportPayloadInput {
  page_id: string;
  page_name: string;
  day: { start: string; end: string };
  watched_senders: string[];
  messages: ChatMessageOut[];
  cards: ChatCard[];
}

export type ExportItemKind = "watched" | "context";

/** Per-card entry — ordered chronologically, mirroring the on-screen
 *  layout. ``kind`` tells consumers whether this message was the target
 *  sender's own ("watched") or a borrowed inline / lead-in
 *  ("context"). For quote cards, the quoted reference is exported
 *  separately on the card itself. */
export interface ExportCardItem {
  kind: ExportItemKind;
  msg_id: string;
}

export type ExportCard =
  | {
      card_index: number;
      kind: "batch";
      target_author: string;
      items: ExportCardItem[];
    }
  | {
      card_index: number;
      kind: "quote";
      target_author: string;
      quoted: QuotedRef;
      items: ExportCardItem[];
    };

export interface ExportMessage extends ChatMessageOut {
  /** Index into ``cards`` — the card this message belongs to. */
  card_index: number;
}

export interface ExportPayload {
  page_id: string;
  page_name: string;
  exported_at: string;
  day: { start: string; end: string };
  watched_senders: string[];
  cards: ExportCard[];
  messages: ExportMessage[];
}

/** Build a self-contained JSON envelope of the rendered cards + messages.
 *  Messages not surfaced in any card are intentionally excluded so the
 *  export mirrors what the operator saw on screen. */
export function buildExportPayload(input: ExportPayloadInput): ExportPayload {
  const cardsOut: ExportCard[] = [];
  const messageIndex = new Map<string, number>();

  input.cards.forEach((card, idx) => {
    const items: ExportCardItem[] = card.items.map((it) => ({
      kind: it.kind,
      msg_id: it.msg.id,
    }));
    for (const it of card.items) messageIndex.set(it.msg.id, idx);

    if (card.kind === "batch") {
      cardsOut.push({
        card_index: idx,
        kind: "batch",
        target_author: card.target_author,
        items,
      });
    } else {
      cardsOut.push({
        card_index: idx,
        kind: "quote",
        target_author: card.target_author,
        quoted: { ...card.quoted },
        items,
      });
    }
  });

  const messagesOut: ExportMessage[] = input.messages
    .filter((m) => messageIndex.has(m.id))
    .map((m) => ({ ...m, card_index: messageIndex.get(m.id)! }));

  return {
    page_id: input.page_id,
    page_name: input.page_name,
    exported_at: new Date().toISOString(),
    day: input.day,
    watched_senders: input.watched_senders,
    cards: cardsOut,
    messages: messagesOut,
  };
}

/** Browser-only helper: serialize ``payload`` and trigger a save-as
 *  download via a transient ``<a download>`` element. */
export function triggerJsonDownload(filename: string, payload: ExportPayload): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), {
    href: url,
    download: filename,
  });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
