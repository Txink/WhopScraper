import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TopBar } from "./TopBar";
import { useViewStore } from "../stores/view";

describe("TopBar", () => {
  beforeEach(() => {
    useViewStore.setState({ view: "dashboard" });
  });

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

  it("renders view-switcher buttons", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.getByRole("button", { name: "监控看板" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Whop 管理" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "数据库" })).toBeInTheDocument();
  });

  it("hides whop status indicator on the right", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.queryByText(/^whop$/i)).toBeNull();
    expect(screen.getByText(/^longport$/i)).toBeInTheDocument();
  });

  it("clicking Whop 管理 updates view store", () => {
    useViewStore.setState({ view: "dashboard" });
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Whop 管理" }));
    expect(useViewStore.getState().view).toBe("whop");
  });

  it("clicking 数据库 updates view store", () => {
    useViewStore.setState({ view: "dashboard" });
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    fireEvent.click(screen.getByRole("button", { name: "数据库" }));
    expect(useViewStore.getState().view).toBe("database");
  });

  it("dashboard button has active class when view='dashboard'", () => {
    useViewStore.setState({ view: "dashboard" });
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    const dashBtn = screen.getByRole("button", { name: "监控看板" });
    expect(dashBtn.className).toContain("active");
    const whopBtn = screen.getByRole("button", { name: "Whop 管理" });
    expect(whopBtn.className).not.toContain("active");
  });

  it("whop button has active class when view='whop'", () => {
    useViewStore.setState({ view: "whop" });
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    const whopBtn = screen.getByRole("button", { name: "Whop 管理" });
    expect(whopBtn.className).toContain("active");
    const dashBtn = screen.getByRole("button", { name: "监控看板" });
    expect(dashBtn.className).not.toContain("active");
  });

  it("database button has active class when view='database'", () => {
    useViewStore.setState({ view: "database" });
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    const dbBtn = screen.getByRole("button", { name: "数据库" });
    expect(dbBtn.className).toContain("active");
    const dashBtn = screen.getByRole("button", { name: "监控看板" });
    expect(dashBtn.className).not.toContain("active");
  });

  it("renders logout button when onLogout provided", () => {
    const fn = vi.fn();
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} onLogout={fn} />);
    const btn = screen.getByRole("button", { name: /退出登录/ });
    fireEvent.click(btn);
    expect(fn).toHaveBeenCalled();
  });

  it("does not render logout button when onLogout absent", () => {
    render(<TopBar connWhop="up" connLongport="up" mode="paper" dryRun={true} />);
    expect(screen.queryByRole("button", { name: /退出登录/ })).toBeNull();
  });
});
