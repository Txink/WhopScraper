import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SignalBubble } from "./SignalBubble";
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
});
