import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PositionsTable } from "./PositionsTable";

describe("PositionsTable", () => {
  it("mobile card shows code and shares", () => {
    render(<PositionsTable positions={[{ code: "600519.SH", shares: 100, cost: 1500 }]}
      forceMobile={true} />);
    expect(screen.getByText("600519.SH")).toBeInTheDocument();
    expect(screen.getByText(/100/)).toBeInTheDocument();
  });
});
