import type { PushEvent } from "../../api/domain-types";
import { paletteColorFor } from "./avatarPalette";
import { SignalCard } from "./SignalCard";
import type { StreamGroup } from "./chatTimeline";

interface StreamViewProps {
  groups: StreamGroup[];
  watched: Set<string>;
  pushEventsByTask: Record<string, PushEvent[]>;
  /** which signal-task id (if any) is currently expanded — single
   *  accordion across the entire view. */
  expandedTaskId: string | null;
  onToggleTask(taskId: string): void;
  autoTrade: boolean;
}

function fmtTime(iso: string): string {
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function StreamView({
  groups, watched, pushEventsByTask, expandedTaskId, onToggleTask, autoTrade,
}: StreamViewProps): JSX.Element {
  return (
    <div className="stream-view">
      {groups.map((g, i) => {
        const isWatched = watched.has(g.sender);
        const headTime = g.kind === "msgs" ? g.entries[0].posted_at : g.task.message.posted_at;
        return (
          <div
            key={`${i}-${g.sender}`}
            className={`stream-group${isWatched ? " watched" : ""}`}
            data-sender={g.sender}
          >
            <div className="chat-stream-head">
              <span className="avatar-sm" style={{ background: paletteColorFor(g.sender) }}>
                {g.sender.slice(-1)}
              </span>
              <span className="stream-author">{g.sender}</span>
              <span className="stream-time">{fmtTime(headTime)}</span>
            </div>
            <div className="stream-body">
              {g.kind === "msgs"
                ? g.entries.map((m) => (
                    <div key={m.id} className="stream-bubble">{m.content}</div>
                  ))
                : (
                  <SignalCard
                    task={g.task}
                    pushEvents={pushEventsByTask[g.task.id] ?? []}
                    expanded={expandedTaskId === g.task.id}
                    onToggle={() => onToggleTask(g.task.id)}
                    autoTrade={autoTrade}
                  />
                )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
