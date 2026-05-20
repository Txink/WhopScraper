import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageShell } from "./MessageShell";

describe("MessageShell", () => {
  it("left · default", () => {
    const { container } = render(
      <MessageShell sender="alpha" firstAt="2026-05-21T01:00:00Z" align="left">
        <div className="chat-group-bubble">hello</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("right · watched sender (iMessage-style)", () => {
    const { container } = render(
      <MessageShell sender="alpha" firstAt="2026-05-21T01:00:00Z" align="right">
        <div className="chat-group-bubble">hello</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("monitor-stock-tone · author renders in source-stock color", () => {
    const { container } = render(
      <MessageShell
        sender="TSLL 监听"
        firstAt="2026-05-21T01:00:00Z"
        align="left"
        senderTone="stock"
      >
        <div className="signal-bubble stock">…</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("monitor-option-tone · author renders in source-option color", () => {
    const { container } = render(
      <MessageShell
        sender="NVDA 期权监听"
        firstAt="2026-05-21T01:00:00Z"
        align="left"
        senderTone="option"
      >
        <div className="signal-bubble option">…</div>
      </MessageShell>,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
