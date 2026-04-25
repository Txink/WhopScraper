import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Login } from "./Login";

describe("Login", () => {
  it("renders brand + form", () => {
    render(<Login />);
    expect(screen.getByText("Signal Station")).toBeInTheDocument();
    expect(screen.getByLabelText(/APP TOKEN/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /进入/ })).toBeInTheDocument();
  });

  it("shows error hint when provided", () => {
    render(<Login errorHint="token 无效" />);
    expect(screen.getByText(/token 无效/)).toBeInTheDocument();
  });

  it("does not show error hint when absent", () => {
    render(<Login />);
    expect(screen.queryByText(/token 无效/)).toBeNull();
  });

  it("disables submit when input empty", () => {
    render(<Login />);
    const button = screen.getByRole("button", { name: /进入/ });
    expect(button).toBeDisabled();
  });

  it("enables submit when input has value", () => {
    render(<Login />);
    const input = screen.getByLabelText(/APP TOKEN/i);
    fireEvent.change(input, { target: { value: "my-token" } });
    const button = screen.getByRole("button", { name: /进入/ });
    expect(button).not.toBeDisabled();
  });

  it("saves token to localStorage on submit", async () => {
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    // Stub out window.location.reload so jsdom doesn't error
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      value: { ...window.location, reload: reloadSpy },
      writable: true,
    });

    render(<Login />);
    const input = screen.getByLabelText(/APP TOKEN/i);
    fireEvent.change(input, { target: { value: "test-token-123" } });
    fireEvent.click(screen.getByRole("button", { name: /进入/ }));

    expect(setItemSpy).toHaveBeenCalledWith("APP_TOKEN", "test-token-123");

    setItemSpy.mockRestore();
  });
});
