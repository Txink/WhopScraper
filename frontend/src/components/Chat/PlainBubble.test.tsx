import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
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

describe("PlainBubble image rendering", () => {
  it("renders <img> when imageUrl is set", () => {
    // Image is decorative (alt=""), so getByRole("img") doesn't match —
    // query by element instead. The caption text is still in the DOM.
    const { container } = render(
      <PlainBubble content="caption" imageUrl="/api/chat-images/abc" />,
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute("src", "/api/chat-images/abc");
    expect(screen.getByText("caption")).toBeInTheDocument();
  });

  it("renders image-only bubble (with marker class) when content is empty", () => {
    const { container } = render(
      <PlainBubble content="" imageUrl="/api/chat-images/abc" />,
    );
    expect(container.querySelector("img")).not.toBeNull();
    expect(
      container.querySelector(".chat-group-bubble--image-only"),
    ).toBeTruthy();
  });

  it("renders no <img> when imageUrl is null/undefined", () => {
    const { container } = render(<PlainBubble content="just text" />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("just text")).toBeInTheDocument();
  });
});
