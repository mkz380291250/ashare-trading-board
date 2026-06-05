import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TrackTable } from "./TrackTable";

const ROWS = [{ code: "601991.SH", added_on: "2026-06-02", name: "大唐发电",
  entry_close: 9.18, ret_since: -0.04, max_gain: 0, max_drawdown: -0.04,
  last_close: 8.81, signal: "buy", buy_price: 8.54,
  ret_t1: null, ret_t3: null, ret_t5: null, ret_t10: null }];

describe("TrackTable", () => {
  it("mobile card shows name + code", () => {
    render(<TrackTable rows={ROWS as any} onRemove={vi.fn()} forceMobile={true} />);
    expect(screen.getByText("大唐发电")).toBeInTheDocument();
    expect(screen.getByText("601991.SH")).toBeInTheDocument();
  });
});
