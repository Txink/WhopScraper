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

  it("calls onSelect with the clicked week's key and collapses", () => {
    const onSelect = vi.fn();
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
    expect(onSelect).toHaveBeenCalledWith("2026-04-12");
    // Strip should be gone (collapsed back to a single chip).
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("renders a non-interactive single chip with no caret when only one week is available", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />);
    const chip = screen.getByRole("button", { name: /04\/19 ~ 04\/25/ });
    expect(chip).toBeDisabled();
    expect(chip.querySelector(".week-paginator-caret")).toBeNull();
  });

  it("collapses when the user clicks outside the strip", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(
      <div>
        <WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />
        <div data-testid="outside">elsewhere</div>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("scrolls the strip so the current chip is centered when current is mid-list", () => {
    const weeks = [
      W("2026-04-26", "04/26", "05/02"),
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
      W("2026-04-05", "04/05", "04/11"),
      W("2026-03-29", "03/29", "04/04"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
    const strip = screen.getByRole("listbox") as HTMLElement;
    // Current is index 2 of 5. The component should set scrollLeft so that
    // index 2 is in the middle of the visible 3-chip viewport — i.e., the
    // strip's data-scroll-mode attribute should be "center".
    expect(strip.dataset.scrollMode).toBe("center");
  });

  it("left-aligns when current is the newest week (index 0)", () => {
    const weeks = [
      W("2026-04-26", "04/26", "05/02"),
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-26" onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/26 ~ 05\/02/ }));
    expect((screen.getByRole("listbox") as HTMLElement).dataset.scrollMode).toBe("start");
  });

  it("right-aligns when current is the oldest week (last index)", () => {
    const weeks = [
      W("2026-04-26", "04/26", "05/02"),
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
    expect((screen.getByRole("listbox") as HTMLElement).dataset.scrollMode).toBe("end");
  });
});
