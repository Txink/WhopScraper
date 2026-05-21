import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OptionCard } from "./OptionCard";
import { makeOptionTask } from "../../test/fixtures";

describe("OptionCard", () => {
  it("folded · contract label 880C 12/15", () => {
    const { container } = render(
      <OptionCard
        monitorName="NVDA 期权监听"
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={false}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("expanded · strike/expiry detail visible", () => {
    const { container } = render(
      <OptionCard
        monitorName="NVDA 期权监听"
        task={makeOptionTask()}
        pushEvents={[]}
        expanded={true}
        onToggle={() => {}}
        autoTrade={true}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
