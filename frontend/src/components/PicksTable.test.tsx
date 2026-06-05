import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PicksTable } from "./PicksTable";

const PICKS = [{ code: "600519.SH", theme: "白酒", first_selected_on: "2026-06-02",
  entry_close: 1500, ret_t1: 0.01, ret_t3: -0.02, ret_t5: null, ret_t10: null }];

describe("PicksTable", () => {
  it("desktop shows table header", () => {
    render(<PicksTable picks={PICKS as any} forceMobile={false} />);
    expect(screen.getByText("代码")).toBeInTheDocument();
  });
  it("mobile shows a card with code + theme", () => {
    render(<PicksTable picks={PICKS as any} forceMobile={true} />);
    expect(screen.getByText("600519.SH")).toBeInTheDocument();
    expect(screen.getByText("白酒")).toBeInTheDocument();
  });
});
