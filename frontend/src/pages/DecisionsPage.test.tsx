import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DecisionsPage } from "./DecisionsPage";

const LIST = [{ id: 1, code: "600519.SH", action: "HOLD", status: "PENDING" }];
const DETAIL = {
  id: 1, code: "600519.SH", name: null, action: "HOLD", confidence: 0.62,
  shares: 0, status: "PENDING", summary: "空仓观望",
  roles: [{ role: "量价分析师", stage: "analyst", stance: "bull",
    action: null, confidence: 0.7, text: "放量突破" }],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = /\/api\/decisions\/1$/.test(url) ? DETAIL : LIST;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }) as any);
});

describe("DecisionsPage", () => {
  it("loads list then detail with role viewpoints", async () => {
    render(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText("空仓观望")).toBeInTheDocument());
    expect(screen.getByText("分析师团")).toBeInTheDocument();
    expect(screen.getByText("放量突破")).toBeInTheDocument();
  });
});
