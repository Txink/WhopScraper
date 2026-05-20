import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlainBubble } from "./PlainBubble";

describe("PlainBubble", () => {
  it("short · plain text", () => {
    const { container } = render(<PlainBubble content="hi" />);
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("long · multi-line content", () => {
    const { container } = render(
      <PlainBubble content={"line 1\nline 2\nline 3 with more text"} />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("with-quoted · embeds quoted preview", () => {
    const { container } = render(
      <PlainBubble
        content="same — also stalking NVDA 880C"
        quoted={{ author: "alpha", content: "if we break 470 i'm taking calls" }}
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
