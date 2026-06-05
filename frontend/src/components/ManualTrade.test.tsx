import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ManualTrade } from "./ManualTrade";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve({}) })) as any);
});

describe("ManualTrade", () => {
  it("submits a BUY to /api/trade", async () => {
    const onDone = vi.fn();
    render(<ManualTrade code="600519.SH" onDone={onDone} />);
    fireEvent.click(screen.getByText("买入"));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
  });
});
