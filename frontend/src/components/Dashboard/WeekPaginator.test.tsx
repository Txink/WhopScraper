import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WeekPaginator } from "./WeekPaginator";
import type { WeekInfo } from "./weekUtils";

const W = (key: string, startLabel: string, endLabel: string): WeekInfo => ({ key, startLabel, endLabel });

describe("<WeekPaginator>", () => {
  it("renders a single chip showing the current week's range when collapsed", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ })).toBeInTheDocument();
    // The other week should not be visible while collapsed.
    expect(screen.queryByText("04/12 ~ 04/18")).toBeNull();
  });

  it("expands on click to reveal all weeks, with the current one selected", () => {
    const weeks = [
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
      W("2026-04-05", "04/05", "04/11"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining("04/19 ~ 04/25"),
      expect.stringContaining("04/12 ~ 04/18"),
      expect.stringContaining("04/05 ~ 04/11"),
    ]);
    expect(screen.getByRole("option", { selected: true }).textContent).toContain("04/12 ~ 04/18");
  });
});
