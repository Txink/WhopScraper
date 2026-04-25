import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TopBar } from "./TopBar";

describe("TopBar", () => {
  it("renders brand + subtitle", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.getByText("Signal Station")).toBeInTheDocument();
    expect(screen.getByText("whop → longport")).toBeInTheDocument();
  });

  it("shows PAPER · DRY pill for paper + dry_run", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.getByText(/PAPER/)).toBeInTheDocument();
    expect(screen.getByText(/DRY/)).toBeInTheDocument();
  });

  it("shows REAL · LIVE pill for real + no dry_run", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="real" dryRun={false} />);
    expect(screen.getByText(/REAL/)).toBeInTheDocument();
    expect(screen.getByText(/LIVE/)).toBeInTheDocument();
  });

  it("includes all 5 filter buttons", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    ["全部", "正股", "期权", "已成交", "解析失败"].forEach((label) => {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    });
  });
});
