import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WeekPaginator } from "./WeekPaginator";
import type { WeekInfo } from "./weekUtils";

const W = (key: string, startLabel: string, endLabel: string): WeekInfo => ({ key, startLabel, endLabel });

const ITEM_H = 26;

function getWheel(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".week-paginator-wheel");
}
function getFrame(): HTMLElement | null {
  return document.querySelector<HTMLElement>(".week-paginator-frame");
}
function scrollWheel(wheel: HTMLElement, scrollTop: number) {
  Object.defineProperty(wheel, "scrollTop", { value: scrollTop, configurable: true });
  fireEvent.scroll(wheel);
}

describe("<WeekPaginator>", () => {
  it("renders the chip with the current week's range when collapsed", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ })).toBeInTheDocument();
    expect(getWheel()).toBeNull();
  });

  it("expands on click and shows every week as an option, with the current week centered", () => {
    const weeks = [
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
      W("2026-04-05", "04/05", "04/11"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
    const wheel = getWheel();
    expect(wheel).not.toBeNull();
    expect(wheel?.dataset.centeredKey).toBe("2026-04-12");
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual([
      "04/19 ~ 04/25",
      "04/12 ~ 04/18",
      "04/05 ~ 04/11",
    ]);
    // Wheel is auto-scrolled so the current week sits in the middle slot.
    expect(wheel?.scrollTop).toBe(ITEM_H);
    // Frame is rendered (visual selection-frame container).
    expect(getFrame()).not.toBeNull();
  });

  it("updates the centered week as the wheel scrolls and mirrors it on the chip text", () => {
    const weeks = [
      W("2026-04-26", "04/26", "05/02"),
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-26" onSelect={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/26 ~ 05\/02/ }));
    const wheel = getWheel()!;
    expect(wheel.dataset.centeredKey).toBe("2026-04-26");
    scrollWheel(wheel, ITEM_H);
    expect(wheel.dataset.centeredKey).toBe("2026-04-19");
    // Chip text now reflects the centered candidate.
    expect(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ })).toBeInTheDocument();
    // Out-of-range scroll clamps to the last index.
    scrollWheel(wheel, ITEM_H * 99);
    expect(wheel.dataset.centeredKey).toBe("2026-04-12");
  });

  it("commits the centered week when the chip is clicked a second time", () => {
    const onSelect = vi.fn();
    const weeks = [
      W("2026-04-26", "04/26", "05/02"),
      W("2026-04-19", "04/19", "04/25"),
      W("2026-04-12", "04/12", "04/18"),
    ];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-26" onSelect={onSelect} />);
    const chip = screen.getByRole("button", { name: /04\/26 ~ 05\/02/ });
    fireEvent.click(chip);
    const wheel = getWheel()!;
    scrollWheel(wheel, ITEM_H * 2); // bring 04/12 into the chip frame
    // Chip is now showing the centered candidate.
    fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
    expect(onSelect).toHaveBeenCalledWith("2026-04-12");
    expect(getWheel()).toBeNull();
  });

  it("does not call onSelect when the centered week is unchanged on chip click", () => {
    const onSelect = vi.fn();
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={onSelect} />);
    const chip = screen.getByRole("button", { name: /04\/19 ~ 04\/25/ });
    fireEvent.click(chip);
    fireEvent.click(chip); // commit, but centered == current
    expect(onSelect).not.toHaveBeenCalled();
    expect(getWheel()).toBeNull();
  });

  it("calls onSelect immediately when a row is clicked directly", () => {
    const onSelect = vi.fn();
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
    expect(onSelect).toHaveBeenCalledWith("2026-04-12");
    expect(getWheel()).toBeNull();
  });

  it("renders a non-interactive single chip with no caret when only one week is available", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />);
    const chip = screen.getByRole("button", { name: /04\/19 ~ 04\/25/ });
    expect(chip).toBeDisabled();
    expect(chip.querySelector(".week-paginator-caret")).toBeNull();
  });

  it("collapses when the user clicks outside the wheel", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(
      <div>
        <WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />
        <div data-testid="outside">elsewhere</div>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    expect(getWheel()).not.toBeNull();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(getWheel()).toBeNull();
  });
});
