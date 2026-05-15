import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { CardCompact } from "./CardCompact";
import { CardExpanded } from "./CardExpanded";

export interface CardProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  /** Controlled: parent decides whether this card is the one currently
   *  expanded (single-accordion semantics — only one card expanded per
   *  tab at a time). */
  expanded: boolean;
  /** Click the card header → parent toggles. */
  onToggle(): void;
  autoTrade: boolean;
}

export function Card({ task, pushEvents, expanded, onToggle, autoTrade }: CardProps) {
  if (expanded) {
    return (
      <CardExpanded
        task={task}
        pushEvents={pushEvents}
        autoTrade={autoTrade}
        onCollapse={onToggle}
      />
    );
  }
  return <CardCompact task={task} autoTrade={autoTrade} onExpand={onToggle} />;
}
