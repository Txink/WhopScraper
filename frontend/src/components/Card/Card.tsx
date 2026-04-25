import { useState } from "react";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { CardCompact } from "./CardCompact";
import { CardExpanded } from "./CardExpanded";

export interface CardProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  defaultExpanded: boolean;
}

export function Card({ task, pushEvents, defaultExpanded }: CardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (expanded) {
    return (
      <CardExpanded
        task={task}
        pushEvents={pushEvents}
        onCollapse={() => setExpanded(false)}
      />
    );
  }
  return <CardCompact task={task} onExpand={() => setExpanded(true)} />;
}
