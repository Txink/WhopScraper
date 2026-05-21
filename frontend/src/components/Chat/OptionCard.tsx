import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { MessageShell } from "./MessageShell";
import { SignalBubble } from "./SignalBubble";

export interface OptionCardProps {
  monitorName: string;
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
  align: "left" | "right";
}

export function OptionCard({
  monitorName, task, pushEvents, expanded, onToggle, autoTrade, align,
}: OptionCardProps): JSX.Element {
  return (
    <MessageShell
      sender={monitorName}
      firstAt={task.message.posted_at}
      align={align}
      senderTone="option"
    >
      <SignalBubble
        task={task}
        pushEvents={pushEvents}
        expanded={expanded}
        onToggle={onToggle}
        autoTrade={autoTrade}
        variant="option"
      />
    </MessageShell>
  );
}
