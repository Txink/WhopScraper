import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TickerWhitelistEditor } from "./TickerWhitelistEditor";

describe("TickerWhitelistEditor", () => {
  it("renders one chip per ticker (with .US suffix)", () => {
    render(
      <TickerWhitelistEditor
        tickers={{ TSLA: { trade_quantity: 100 }, AAPL: { trade_quantity: 50 } }}
        onChange={() => {}}
      />
    );
    expect(screen.getByText("TSLA.US")).toBeInTheDocument();
    expect(screen.getByText("AAPL.US")).toBeInTheDocument();
  });

  it("clicking a chip calls onChange with that ticker removed", () => {
    const onChange = vi.fn();
    render(
      <TickerWhitelistEditor
        tickers={{ TSLA: { trade_quantity: 100 } }}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText("删除 TSLA"));
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("filling add-form + clicking add appends a new ticker (uppercased) and clears draft", () => {
    const onChange = vi.fn();
    const { container } = render(
      <TickerWhitelistEditor
        tickers={{}}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    const symbolInput = container.querySelector('input[placeholder="ticker"]')!;
    const qtyInput = container.querySelector('input[placeholder="qty"]')!;
    fireEvent.change(symbolInput, { target: { value: "nvda" } });
    fireEvent.change(qtyInput, { target: { value: "200" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(onChange).toHaveBeenCalledWith({ NVDA: { trade_quantity: 200 } });
    expect((symbolInput as HTMLInputElement).value).toBe("");
  });

  it("shows form error when ticker is empty", () => {
    render(
      <TickerWhitelistEditor
        tickers={{}}
        onChange={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "100" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(screen.getByRole("alert")).toHaveTextContent("ticker 不能为空");
  });

  it("shows form error for non-positive quantity", () => {
    render(
      <TickerWhitelistEditor
        tickers={{}}
        onChange={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("ticker"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "0" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(screen.getByRole("alert")).toHaveTextContent(/数量必须是 > 0/);
  });

  it("shows form error for duplicate ticker", () => {
    render(
      <TickerWhitelistEditor
        tickers={{ TSLL: { trade_quantity: 2000 } }}
        onChange={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.change(screen.getByPlaceholderText("ticker"), { target: { value: "tsll" } });
    fireEvent.change(screen.getByPlaceholderText("qty"), { target: { value: "100" } });
    fireEvent.click(screen.getByLabelText("确认添加"));
    expect(screen.getByRole("alert")).toHaveTextContent(/已存在/);
  });

  it("disabled prop disables chips and inputs", () => {
    render(
      <TickerWhitelistEditor
        tickers={{ TSLA: { trade_quantity: 1 } }}
        onChange={() => {}}
        disabled
      />
    );
    expect(screen.getByLabelText("删除 TSLA")).toBeDisabled();
    expect(screen.getByLabelText("添加 ticker")).toBeDisabled();
  });

  it("renders API error when error prop is set", () => {
    render(
      <TickerWhitelistEditor
        tickers={{}}
        onChange={() => {}}
        error="network failure"
      />
    );
    expect(screen.getByText("network failure")).toBeInTheDocument();
  });

  it("cancel button closes the inline form without calling onChange", () => {
    const onChange = vi.fn();
    render(
      <TickerWhitelistEditor
        tickers={{}}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByLabelText("添加 ticker"));
    fireEvent.click(screen.getByLabelText("取消"));
    expect(screen.queryByPlaceholderText("ticker")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });
});
