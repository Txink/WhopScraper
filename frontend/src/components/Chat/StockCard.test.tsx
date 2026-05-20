import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StockCard } from "./StockCard";
import {
  makeStockTask,
  makeFailedParseTask,
} from "../../test/fixtures";

describe("StockCard", () => {
  it("folded · filled order", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeStockTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("expanded · detail visible inside shell", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeStockTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("parse-error · red sig", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeFailedParseTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("order-pending · INSTRUCTION_READY shows confirm pair when autoTrade=false", () => {
    const { container } = render(
      <StockCard
        monitorName="TSLL 监听"
        task={makeStockTask({ status: "INSTRUCTION_READY" })}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={false}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
