import type { TaskSummary } from "../../api/domain-types";
import type { ChatMessageOut } from "./chatCards";

export type TimelineEntry =
  | { kind: "msg"; msg: ChatMessageOut }
  | { kind: "signal"; task: TaskSummary };

function postedAt(e: TimelineEntry): string {
  return e.kind === "msg" ? e.msg.posted_at : e.task.message.posted_at;
}

export function buildTimeline(
  messages: ChatMessageOut[],
  tasks: TaskSummary[],
  _urlToMonitorName: Record<string, string>,
): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...messages.map((m): TimelineEntry => ({ kind: "msg", msg: m })),
    ...tasks.map((t): TimelineEntry => ({ kind: "signal", task: t })),
  ];
  // String compare on ISO timestamps is correct as long as zones are consistent;
  // chat-board messages and broker-side tasks both store UTC ISO with Z.
  entries.sort((a, b) => postedAt(a).localeCompare(postedAt(b)));
  return entries;
}

export type FilterBlock =
  | { kind: "chat"; sender: string; messages: ChatMessageOut[] }
  | { kind: "aggregate-stock"; tasks: TaskSummary[]; monitorNames: string[] }
  | { kind: "aggregate-option"; tasks: TaskSummary[]; monitorNames: string[] };

/** Filter mode: build per-watched-sender chat blocks + 0-1 aggregate stock
 *  block + 0-1 aggregate option block. ``watched`` is the union of selected
 *  sender chip names (humans + monitor names). */
export function buildFilterBlocks(
  timeline: TimelineEntry[],
  watched: Set<string>,
  urlToMonitorName: Record<string, string> = {},
): FilterBlock[] {
  const bySender = new Map<string, ChatMessageOut[]>();
  const stockTasks: TaskSummary[] = [];
  const optionTasks: TaskSummary[] = [];
  const stockMonitors = new Set<string>();
  const optionMonitors = new Set<string>();

  for (const e of timeline) {
    if (e.kind === "msg") {
      if (!watched.has(e.msg.author)) continue;
      const list = bySender.get(e.msg.author) ?? [];
      list.push(e.msg);
      bySender.set(e.msg.author, list);
    } else {
      const name = urlToMonitorName[e.task.message.url ?? ""] ?? "(unknown)";
      if (!watched.has(name)) continue;
      if (e.task.type === "option") {
        optionTasks.push(e.task);
        optionMonitors.add(name);
      } else {
        stockTasks.push(e.task);
        stockMonitors.add(name);
      }
    }
  }

  const blocks: FilterBlock[] = [];
  for (const [sender, messages] of bySender) {
    blocks.push({ kind: "chat", sender, messages });
  }
  if (stockTasks.length > 0) {
    blocks.push({
      kind: "aggregate-stock", tasks: stockTasks,
      monitorNames: [...stockMonitors],
    });
  }
  if (optionTasks.length > 0) {
    blocks.push({
      kind: "aggregate-option", tasks: optionTasks,
      monitorNames: [...optionMonitors],
    });
  }
  return blocks;
}

export type StreamGroup =
  | { kind: "msgs"; sender: string; entries: ChatMessageOut[] }
  | { kind: "signal"; sender: string; task: TaskSummary };

/** Highlight (stream) mode: flat chronological list, consecutive same-
 *  sender msg entries merged. Signals are always their own group. */
export function buildStreamGroups(
  timeline: TimelineEntry[],
  urlToMonitorName: Record<string, string> = {},
): StreamGroup[] {
  const out: StreamGroup[] = [];
  let pending: { sender: string; entries: ChatMessageOut[] } | null = null;
  const flush = () => {
    if (pending) {
      out.push({ kind: "msgs", sender: pending.sender, entries: pending.entries });
      pending = null;
    }
  };

  for (const e of timeline) {
    if (e.kind === "msg") {
      const sender = e.msg.author;
      if (pending && pending.sender === sender) {
        pending.entries.push(e.msg);
      } else {
        flush();
        pending = { sender, entries: [e.msg] };
      }
    } else {
      flush();
      const sender = urlToMonitorName[e.task.message.url ?? ""] ?? "(unknown)";
      out.push({ kind: "signal", sender, task: e.task });
    }
  }
  flush();
  return out;
}
