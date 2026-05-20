import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatMessage } from "./ChatMessage";
import {
  makeMessage,
  makeConsecutiveMessages,
  makeQuotedMessage,
} from "../../test/fixtures";

describe("ChatMessage", () => {
  it("single · one bubble under one head", () => {
    const m = makeMessage({ author: "alpha", content: "hi" });
    const { container } = render(
      <ChatMessage
        sender="alpha"
        firstAt={m.posted_at}
        messages={[m]}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("consecutive-3-msgs · three bubbles share one head", () => {
    const list = makeConsecutiveMessages("bob", ["first", "second", "third"]);
    const { container } = render(
      <ChatMessage
        sender="bob"
        firstAt={list[0].posted_at}
        messages={list}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("right-aligned · watched sender renders chat-group--right", () => {
    const m = makeMessage({ author: "carol", content: "watched-msg" });
    const { container } = render(
      <ChatMessage
        sender="carol"
        firstAt={m.posted_at}
        messages={[m]}
        align="right"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });

  it("with-quoted · embeds quoted preview in bubble", () => {
    const m = makeQuotedMessage("alpha", "agreed", { author: "bob", content: "long NVDA" });
    const { container } = render(
      <ChatMessage
        sender="alpha"
        firstAt={m.posted_at}
        messages={[m]}
        align="left"
      />,
    );
    expect(container.innerHTML).toMatchSnapshot();
  });
});
