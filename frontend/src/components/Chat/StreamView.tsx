import type { PushEvent } from "../../api/domain-types";
import type { StreamGroup } from "./chatTimeline";
import { ChatMessage } from "./ChatMessage";
import { StockCard } from "./StockCard";
import { OptionCard } from "./OptionCard";

export interface StreamViewProps {
  groups: StreamGroup[];
  watched: Set<string>;
  pushEventsByTask: Record<string, PushEvent[]>;
  /** which signal-task id (if any) is currently expanded — single
   *  accordion across the entire view. */
  expandedTaskId: string | null;
  onToggleTask(taskId: string): void;
  autoTrade: boolean;
}

export function StreamView({
  groups, watched, pushEventsByTask, expandedTaskId, onToggleTask, autoTrade,
}: StreamViewProps): JSX.Element {
  return (
    <div className="stream-view">
      {groups.map((g, i) => {
        const align: "left" | "right" = watched.has(g.sender) ? "right" : "left";
        if (g.kind === "msgs") {
          return (
            <ChatMessage
              key={`${i}-${g.sender}`}
              sender={g.sender}
              firstAt={g.entries[0].posted_at}
              messages={g.entries}
              align={align}
            />
          );
        }
        const Card = g.task.type === "option" ? OptionCard : StockCard;
        return (
          <Card
            key={`${i}-${g.sender}`}
            monitorName={g.sender}
            task={g.task}
            pushEvents={pushEventsByTask[g.task.id] ?? []}
            expanded={expandedTaskId === g.task.id}
            onToggle={() => onToggleTask(g.task.id)}
            autoTrade={autoTrade}
            align={align}
          />
        );
      })}
    </div>
  );
}
