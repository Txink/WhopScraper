import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TopBar } from "./TopBar";
import { useViewStore } from "../stores/view";

describe("TopBar", () => {
  beforeEach(() => {
    useViewStore.setState({ view: "dashboard" });
  });

  it("renders brand + subtitle", () => {
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.getByText("Signal Station")).toBeInTheDocument();
    expect(screen.queryByText("whop → longport")).toBeNull();
  });

  it("shows PAPER · DRY pill for paper + dry_run", () => {
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.getByText(/PAPER/)).toBeInTheDocument();
    expect(screen.getByText(/DRY/)).toBeInTheDocument();
  });

  it("shows REAL · LIVE pill for real + no dry_run", () => {
    render(<TopBar connLongport="up" mode="real" dryRun={false} />);
    expect(screen.getByText(/REAL/)).toBeInTheDocument();
    expect(screen.getByText(/LIVE/)).toBeInTheDocument();
  });

  it("shows AUTO in pill when autoTrade enabled", () => {
    render(<TopBar connLongport="up" mode="paper" dryRun={true} autoTrade={true} />);
    expect(screen.getByText("PAPER · DRY · AUTO")).toBeInTheDocument();
  });

  it("renders view-switcher buttons", () => {
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.getByRole("button", { name: "监控看板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "数据库" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Whop 管理/ })).toBeNull();
  });

  it("hides whop status indicator on the right", () => {
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.queryByText(/^whop$/i)).toBeNull();
    expect(screen.getByText(/^longport$/i)).toBeInTheDocument();
  });

  it("clicking 数据库 updates view store", () => {
    useViewStore.setState({ view: "dashboard" });
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    fireEvent.click(screen.getByRole("button", { name: "数据库" }));
    expect(useViewStore.getState().view).toBe("database");
  });

  it("dashboard button has active class when view='dashboard'", () => {
    useViewStore.setState({ view: "dashboard" });
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    const dashBtn = screen.getByRole("button", { name: "监控看板" });
    expect(dashBtn.className).toContain("active");
    const dbBtn = screen.getByRole("button", { name: "数据库" });
    expect(dbBtn.className).not.toContain("active");
  });

  it("database button has active class when view='database'", () => {
    useViewStore.setState({ view: "database" });
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    const dbBtn = screen.getByRole("button", { name: "数据库" });
    expect(dbBtn.className).toContain("active");
    const dashBtn = screen.getByRole("button", { name: "监控看板" });
    expect(dashBtn.className).not.toContain("active");
  });

  it("renders logout button when onLogout provided", () => {
    const fn = vi.fn();
    render(<TopBar connLongport="up" mode="paper" dryRun={true} onLogout={fn} />);
    const btn = screen.getByRole("button", { name: /退出登录/ });
    fireEvent.click(btn);
    expect(fn).toHaveBeenCalled();
  });

  it("does not render logout button when onLogout absent", () => {
    render(<TopBar connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.queryByRole("button", { name: /退出登录/ })).toBeNull();
  });

  it("clicking PAPER/DRY pill triggers longport settings callback", () => {
    const fn = vi.fn();
    render(
      <TopBar
        connLongport="up"
        mode="paper"
        dryRun={true}
        onOpenLongportSettings={fn}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: /PAPER/i }));
    expect(fn).toHaveBeenCalledOnce();
  });
});
