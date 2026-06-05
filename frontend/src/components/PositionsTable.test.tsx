import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "./PositionsTable";

const POS = [{ code: "600519.SH", name: "贵州茅台", shares: 100, cost: 1500,
  buy_date: "2026-06-01", last_close: 1650, market_value: 165000,
  pnl: 15000, pnl_pct: 0.1 }];

describe("PositionsTable", () => {
  it("mobile card shows name, buy date and pnl", () => {
    render(<PositionsTable positions={POS as any} forceMobile={true} />);
    expect(screen.getByText("贵州茅台")).toBeInTheDocument();
    expect(screen.getByText(/2026-06-01/)).toBeInTheDocument();
    expect(screen.getByText(/15000/)).toBeInTheDocument();
  });
});
