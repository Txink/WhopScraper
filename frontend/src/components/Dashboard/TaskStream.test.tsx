import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { TaskStream } from "./TaskStream";
import { computeWeeks } from "./weekUtils";
import type { TaskSummary } from "../../api/domain-types";

const NOW = new Date(2026, 3, 22, 12, 0, 0); // 2026-04-22 (Wed) → wk 04-19

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

const mkTask = (id: string, postedAt: Date, content = "msg"): TaskSummary =>
  ({
    id,
    status: "FILLED",
    created_at: postedAt.toISOString(),
    updated_at: postedAt.toISOString(),
    message: {
      url: "https://w/x",
      author: "a",
      content,
      posted_at: postedAt.toISOString(),
      received_at: postedAt.toISOString(),
    },
  }) as unknown as TaskSummary;

function renderControlled(tasks: TaskSummary[], currentKey?: string) {
  const { weeks, groups } = computeWeeks(tasks);
  const onSelect = vi.fn();
  const result = render(
    <TaskStream
      pushEventsByTask={{}}
      expandMode="smart"
      autoTrade={false}
      weeks={weeks}
      groups={groups}
      currentWeekKey={currentKey ?? weeks[0]?.key ?? null}
      onSelectWeek={onSelect}
    />,
  );
  return { ...result, onSelect, weeks, groups };
}

describe("<TaskStream> weekly pagination (controlled)", () => {
  it("renders only the selected week's tasks", () => {
    const tasks = [
      mkTask("this-1", new Date(2026, 3, 22, 10), "this week"),
      mkTask("last-1", new Date(2026, 3, 15, 10), "last week"),
    ];
    renderControlled(tasks); // defaults to newest week
    expect(screen.getByText("this week")).toBeInTheDocument();
    expect(screen.queryByText("last week")).toBeNull();
  });

  it("shows the WeekPaginator chip with the current week's range", () => {
    renderControlled([mkTask("a", new Date(2026, 3, 22, 10))]);
    expect(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ })).toBeInTheDocument();
  });

  it("calls onSelectWeek when a different chip is clicked", () => {
    const tasks = [
      mkTask("this-1", new Date(2026, 3, 22, 10)),
      mkTask("last-1", new Date(2026, 3, 15, 10)),
    ];
    const { onSelect } = renderControlled(tasks);
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
    expect(onSelect).toHaveBeenCalledWith("2026-04-12");
  });

  it("renders the previous week's tasks when the controller selects it", () => {
    const tasks = [
      mkTask("this-1", new Date(2026, 3, 22, 10), "this week"),
      mkTask("last-1", new Date(2026, 3, 15, 10), "last week"),
    ];
    renderControlled(tasks, "2026-04-12");
    expect(screen.getByText("last week")).toBeInTheDocument();
    expect(screen.queryByText("this week")).toBeNull();
  });

  it("preserves the existing per-day stream-divider inside a week", () => {
    const tasks = [
      mkTask("today", new Date(2026, 3, 22, 10), "today msg"),
      mkTask("yesterday", new Date(2026, 3, 21, 10), "yesterday msg"),
    ];
    renderControlled(tasks);
    expect(within(document.body).getByText(/今天 2026-04-22/)).toBeInTheDocument();
    expect(within(document.body).getByText(/昨天 2026-04-21/)).toBeInTheDocument();
  });

  it("renders nothing when weeks is empty", () => {
    const { container } = render(
      <TaskStream
        pushEventsByTask={{}}
        expandMode="smart"
        autoTrade={false}
        weeks={[]}
        groups={new Map()}
        currentWeekKey={null}
        onSelectWeek={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
