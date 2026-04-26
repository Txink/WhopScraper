import { useState } from "react";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { CardCompact } from "./CardCompact";
import { CardExpanded } from "./CardExpanded";

export interface CardProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  defaultExpanded: boolean;
  autoTrade: boolean;
}

export function Card({ task, pushEvents, defaultExpanded, autoTrade }: CardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (expanded) {
    return (
      <CardExpanded
        task={task}
        pushEvents={pushEvents}
        autoTrade={autoTrade}
        onCollapse={() => setExpanded(false)}
      />
    );
  }
  return <CardCompact task={task} autoTrade={autoTrade} onExpand={() => setExpanded(true)} />;
}
