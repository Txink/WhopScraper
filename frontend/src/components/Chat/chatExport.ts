import type { ChatCard, ChatMessageOut, QuotedRef } from "./chatCards";

/** Input bundle for {@link buildExportPayload}. The caller is expected to
 *  pass the *already-filtered* watched message list plus the cards derived
 *  from it via {@link groupIntoCards}, so this module does no grouping
 *  work — it just stamps ``card_index`` onto each surviving message and
 *  emits the JSON-friendly envelope. */
export interface ExportPayloadInput {
  page_id: string;
  page_name: string;
  week: { start: string; end: string };
  watched_senders: string[];
  messages: ChatMessageOut[];
  cards: ChatCard[];
}

export type ExportCard =
  | {
      card_index: number;
      kind: "batch";
      target_author: string;
      msg_ids: string[];
    }
  | {
      card_index: number;
      kind: "quote";
      target_msg_id: string;
      quoted: QuotedRef;
    };

export interface ExportMessage extends ChatMessageOut {
  /** Index into ``cards`` — the card this message belongs to. */
  card_index: number;
}

export interface ExportPayload {
  page_id: string;
  page_name: string;
  exported_at: string;
  week: { start: string; end: string };
  watched_senders: string[];
  cards: ExportCard[];
  messages: ExportMessage[];
}

/** Build a self-contained JSON envelope of the rendered cards + messages.
 *  Overflow-clipped messages are intentionally excluded so the export
 *  mirrors what the operator saw on screen. */
export function buildExportPayload(input: ExportPayloadInput): ExportPayload {
  const cardsOut: ExportCard[] = [];
  const messageIndex = new Map<string, number>();

  input.cards.forEach((card, idx) => {
    if (card.kind === "batch") {
      cardsOut.push({
        card_index: idx,
        kind: "batch",
        target_author: card.target_author,
        msg_ids: card.msgs.map((m) => m.id),
      });
      for (const m of card.msgs) messageIndex.set(m.id, idx);
    } else {
      cardsOut.push({
        card_index: idx,
        kind: "quote",
        target_msg_id: card.target.id,
        quoted: { ...card.quoted },
      });
      messageIndex.set(card.target.id, idx);
    }
  });

  const messagesOut: ExportMessage[] = input.messages
    .filter((m) => messageIndex.has(m.id))
    .map((m) => ({ ...m, card_index: messageIndex.get(m.id)! }));

  return {
    page_id: input.page_id,
    page_name: input.page_name,
    exported_at: new Date().toISOString(),
    week: input.week,
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
