import { beforeEach, describe, expect, it } from "vitest";
import type { WhopPage } from "../api/domain-types";
import { useChildPagesStore } from "./childPages";

function makePage(over: Partial<WhopPage>): WhopPage {
  return {
    id: "p1",
    url: "https://x",
    source: "stock",
    name: "P1",
    added_at: new Date().toISOString(),
    settings: { dedupe_processed_messages: true } as WhopPage["settings"],
    running: true,
    started_at: null,
    last_poll_at: null,
    messages_published: 0,
    last_error: null,
    parent_chat_id: "chat1",
    ...over,
  };
}

describe("useChildPagesStore", () => {
  beforeEach(() => {
    useChildPagesStore.setState({ byParent: {} });
  });

  it("setByParent replaces the list for that parent", () => {
    const a = makePage({ id: "a" });
    const b = makePage({ id: "b" });
    useChildPagesStore.getState().setByParent("chat1", [a, b]);
    expect(useChildPagesStore.getState().byParent["chat1"]).toHaveLength(2);
    useChildPagesStore.getState().setByParent("chat1", [a]);
    expect(useChildPagesStore.getState().byParent["chat1"]).toHaveLength(1);
  });

  it("upsert places child under its parent and replaces existing by id", () => {
    const a = makePage({ id: "a", name: "old" });
    useChildPagesStore.getState().upsert(a);
    expect(useChildPagesStore.getState().byParent["chat1"][0].name).toBe("old");
    useChildPagesStore.getState().upsert({ ...a, name: "new" });
    expect(useChildPagesStore.getState().byParent["chat1"][0].name).toBe("new");
  });

  it("upsert moves child between parents when parent_chat_id changes", () => {
    const a = makePage({ id: "a", parent_chat_id: "chat1" });
    useChildPagesStore.getState().upsert(a);
    useChildPagesStore.getState().upsert({ ...a, parent_chat_id: "chat2" });
    expect(useChildPagesStore.getState().byParent["chat1"]).toBeUndefined();
    expect(useChildPagesStore.getState().byParent["chat2"]).toHaveLength(1);
  });

  it("upsert with parent_chat_id=null removes from child store", () => {
    const a = makePage({ id: "a" });
    useChildPagesStore.getState().upsert(a);
    useChildPagesStore.getState().upsert({ ...a, parent_chat_id: null });
    expect(useChildPagesStore.getState().byParent["chat1"] ?? []).toHaveLength(0);
  });

  it("remove drops the child by id", () => {
    useChildPagesStore.getState().upsert(makePage({ id: "a" }));
    useChildPagesStore.getState().remove("a");
    expect(useChildPagesStore.getState().byParent["chat1"] ?? []).toHaveLength(0);
  });

  it("setByParent for a parent with empty list drops that parent's entry entirely (or stores [])", () => {
    useChildPagesStore.getState().setByParent("chat1", [makePage({ id: "a" })]);
    useChildPagesStore.getState().setByParent("chat1", []);
    // Implementation detail: either store [] or drop the key. Both are OK
    // as long as readers treat undefined and [] interchangeably.
    expect(useChildPagesStore.getState().byParent["chat1"] ?? []).toHaveLength(0);
  });
});
