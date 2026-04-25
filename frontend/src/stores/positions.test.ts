import { describe, expect, it, beforeEach } from "vitest";
import { usePositionsStore } from "./positions";

describe("positions store", () => {
  beforeEach(() => {
    usePositionsStore.setState({ stocks: [], options: [] });
  });

  it("setAll stores stocks and options", () => {
    usePositionsStore.getState().setAll({
      stocks: [
        { symbol: "TSLL.US", type: "stock", ticker: "TSLL", quantity: 1500, avg_cost: 22.85 },
      ],
      options: [
        {
          symbol: "TSLA.US 240620 250.0 CALL",
          type: "option",
          ticker: "TSLA",
          quantity: 10,
          avg_cost: 5.5,
          option_strike: 250,
          option_expiry: "2024-06-20",
          option_type: "CALL",
        },
      ],
    });
    expect(usePositionsStore.getState().stocks).toHaveLength(1);
    expect(usePositionsStore.getState().stocks[0].symbol).toBe("TSLL.US");
    expect(usePositionsStore.getState().options).toHaveLength(1);
    expect(usePositionsStore.getState().options[0].ticker).toBe("TSLA");
  });

  it("reset clears stocks and options", () => {
    usePositionsStore.getState().setAll({
      stocks: [
        { symbol: "TSLL.US", type: "stock", ticker: "TSLL", quantity: 1500, avg_cost: 22.85 },
      ],
      options: [],
    });
    usePositionsStore.getState().reset();
    expect(usePositionsStore.getState().stocks).toHaveLength(0);
    expect(usePositionsStore.getState().options).toHaveLength(0);
  });
});
