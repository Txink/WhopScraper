import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { MessageShell } from "./MessageShell";
import { SignalBubble } from "./SignalBubble";

export interface StockCardProps {
  monitorName: string;
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  align: "left" | "right";
}

export function StockCard({
  monitorName, task, pushEvents, expanded, onToggle, autoTrade, align,
}: StockCardProps): JSX.Element {
  return (
    <MessageShell
      sender={monitorName}
      firstAt={task.message.posted_at}
      align={align}
      senderTone="stock"
    >
      <SignalBubble
        task={task}
        pushEvents={pushEvents}
        expanded={expanded}
        onToggle={onToggle}
        autoTrade={autoTrade}
        variant="stock"
      />
    </MessageShell>
  );
}
