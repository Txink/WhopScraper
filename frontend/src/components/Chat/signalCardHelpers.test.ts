import { describe, expect, it } from "vitest";
import { layersForTask } from "./signalCardHelpers";
import type { TaskSummary } from "../../api/domain-types";

function task(over: Partial<TaskSummary>): TaskSummary {
  return {
    id: "t1",
    type: "stock",
    status: "FILLED",
    order_id: null,
    stage_timings: {},
    reject_reason: null,
    message: {
      id: "msg1",
      source: "whop",
      author: "TSLL 监听",
      content: "buying tsla calls dip 200",
      posted_at: "2026-05-20T01:32:15Z",
      received_at: "2026-05-20T01:32:15Z",
      url: "https://whop.com/c/stock-a",
    },
    instruction: {
      type: "stock",
      instruction_type: "BUY",
      ticker: "TSLL",
      symbol: "TSLL.US",
      price: 200,
      quantity: 100,
      price_range: null,
      position_size: null,
      stop_loss_price: null,
      take_profit_price: null,
      context_source: null,
      parser_notes: [],
    },
    last_cum_qty: 100,
    last_cum_avg_price: 199.87,
    created_at: "2026-05-20T01:32:15Z",
    updated_at: "2026-05-20T01:32:16Z",
    ...over,
  } as TaskSummary;
}

describe("layersForTask", () => {
  it("FILLED stock task: ord layer is the cum/avg form with ok dot", () => {
    const layers = layersForTask(task({ status: "FILLED" }));
    expect(layers.kind).toBe("normal");
    expect(layers.ord?.text).toContain("已成交");
    expect(layers.ord?.dot).toBe("ok");
    expect(layers.ord?.cum).toContain("199.87");
  });

  it("PARSE_ERROR: sig layer carries the error message, ord is null", () => {
    const layers = layersForTask(task({
      status: "PARSE_ERROR",
      instruction: null,
      reject_reason: "regex no match",
    }));
    expect(layers.kind).toBe("parse_error");
    expect(layers.sig?.error).toContain("未解析");
    expect(layers.ord).toBeNull();
  });

  it("INSTRUCTION_READY + auto_trade off: sig layer flags confirm pair, ord warn dot", () => {
    const layers = layersForTask(
      task({ status: "INSTRUCTION_READY" }),
      { autoTrade: false }
    );
    expect(layers.sig?.showConfirmActions).toBe(true);
    expect(layers.ord?.dot).toBe("warn");
  });

  it("INSTRUCTION_READY + auto_trade on: no confirm actions surfaced", () => {
    const layers = layersForTask(
      task({ status: "INSTRUCTION_READY" }),
      { autoTrade: true }
    );
    expect(layers.sig?.showConfirmActions).toBe(false);
  });

  it("SKIPPED: ord text contains reject_reason and dot is warn", () => {
    const layers = layersForTask(task({
      status: "SKIPPED",
      reject_reason: "block_historical_messages",
    }));
    expect(layers.ord?.text).toContain("block_historical_messages");
    expect(layers.ord?.dot).toBe("warn");
  });

  it("SUBMIT_FAILED: ord text says '提交失败' and dot is err", () => {
    const layers = layersForTask(task({
      status: "SUBMIT_FAILED",
      reject_reason: "broker rejected",
    }));
    expect(layers.ord?.dot).toBe("err");
    expect(layers.ord?.text).toContain("提交失败");
  });

  it("PARTIAL: ord shows cum/total with warn dot", () => {
    const layers = layersForTask(task({
      status: "PARTIAL",
      last_cum_qty: 60,
      last_cum_avg_price: 201.36,
    }));
    expect(layers.ord?.dot).toBe("warn");
    expect(layers.ord?.text).toContain("部分成交");
    expect(layers.ord?.cum).toContain("60/100");
  });

  it("option task: sig.contract is formatted '880C MM/DD'", () => {
    const layers = layersForTask(task({
      type: "option",
      instruction: {
        type: "option",
        instruction_type: "BUY",
        ticker: "NVDA",
        symbol: "NVDA.US",
        strike: 880,
        expiry: "2026-12-15",
        price: 5.2,
        quantity: 5,
        price_range: null,
        position_size: null,
        stop_loss_price: null,
        take_profit_price: null,
        context_source: null,
        parser_notes: [],
      } as TaskSummary["instruction"],
    }));
    expect(layers.sig?.contract).toBe("880C 12/15");
  });

  it("option PUT task: sig.contract uses 'P' side letter", () => {
    const layers = layersForTask(task({
      type: "option",
      instruction: {
        type: "option",
        instruction_type: "SELL",
        ticker: "NVDA",
        symbol: "NVDA.US",
        option_type: "PUT",
        strike: 880,
        expiry: "2026-12-15",
        price: 3.1,
        quantity: 5,
        price_range: null,
        position_size: null,
        stop_loss_price: null,
        take_profit_price: null,
        context_source: null,
        parser_notes: [],
      } as TaskSummary["instruction"],
    }));
    expect(layers.sig?.contract).toBe("880P 12/15");
  });

  it("stock task: sig.contract is null", () => {
    const layers = layersForTask(task({}));
    expect(layers.sig?.contract).toBeNull();
  });

  it("image message → kind 'image' with imageUrl, no sig/ord", () => {
    const base = task({});
    const t: TaskSummary = {
      ...base,
      status: "SKIPPED",
      instruction: null,
      message: { ...base.message, content: "", image_url: "/api/messages/x/image" },
    };
    const layers = layersForTask(t);
    expect(layers.kind).toBe("image");
    expect(layers.imageUrl).toBe("/api/messages/x/image");
    expect(layers.sig).toBeNull();
    expect(layers.ord).toBeNull();
  });
});
