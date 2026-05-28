import { render, fireEvent } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../api/domain-types";
import { configureHttp, __resetForTests } from "../../api/http";
import { SignalBubble } from "./SignalBubble";

// authedAssetUrl (called when rendering image bubbles) requires HTTP config.
beforeAll(() => {
  configureHttp({ baseUrl: "http://localhost:8000", token: "test-token" });
});
afterAll(() => {
  __resetForTests();
});
import {
  makeStockTask,
  makeOptionTask,
  makeFailedParseTask,
} from "../../test/fixtures";

describe("SignalBubble", () => {
  it("stock-folded · filled order", () => {
    const { container } = render(
      <SignalBubble
        task={makeStockTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        variant="stock"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("stock-expanded · detail block visible", () => {
    const { container } = render(
      <SignalBubble
        task={makeStockTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        variant="stock"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("option-folded · contract label 880C 12/15", () => {
    const { container } = render(
      <SignalBubble
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        variant="option"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("option-expanded · strike/expiry detail visible", () => {
    const { container } = render(
      <SignalBubble
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        variant="option"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("parse-error · red sig + no ord", () => {
    const { container } = render(
      <SignalBubble
        task={makeFailedParseTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        variant="stock"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("order-pending · confirm-pair renders when autoTrade=false + INSTRUCTION_READY", () => {
    const { container } = render(
      <SignalBubble
        task={makeStockTask({ status: "INSTRUCTION_READY" })}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={false}
        variant="stock"
      />,
    );
    expect(container.querySelector(".confirm-pair")).not.toBeNull();
  });

  it("click inside .confirm-pair does NOT fire onToggle", () => {
    const onToggle = vi.fn();
    const { container } = render(
      <SignalBubble
        task={makeStockTask({ status: "INSTRUCTION_READY" })}
        pushEvents={[]}
        expanded={false}
        onToggle={onToggle}
        autoTrade={false}
        variant="stock"
      />,
    );
    const confirmEl = container.querySelector(".confirm-pair");
    expect(confirmEl).not.toBeNull();
    fireEvent.click(confirmEl as Element);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("renders an image bubble for image messages", () => {
    const base = makeStockTask();
    const task: TaskSummary = {
      ...base,
      status: "SKIPPED",
      message: { ...base.message, content: "", image_url: "/api/messages/x/image" },
    };
    const { container } = render(
      <SignalBubble task={task} pushEvents={[]} expanded={false}
        onToggle={() => {}} autoTrade={true} variant="stock" />,
    );
    const img = container.querySelector("img.signal-bubble-image");
    expect(img).not.toBeNull();
    // 不应出现解析报错文案
    expect(container.textContent).not.toContain("未解析");
  });
});
