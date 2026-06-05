import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ConclusionCard } from "./ConclusionCard";

const BASE = { id: 1, code: "600519.SH", name: "贵州茅台", action: "BUY",
  confidence: 0.7, shares: 100, summary: "低估值买入" };

describe("ConclusionCard", () => {
  it("shows action and approve/reject when PENDING", () => {
    render(<ConclusionCard c={{ ...BASE, status: "PENDING" }}
      onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("低估值买入")).toBeInTheDocument();
    expect(screen.getByText("批准")).toBeInTheDocument();
    expect(screen.getByText("驳回")).toBeInTheDocument();
  });

  it("hides buttons when not PENDING", () => {
    render(<ConclusionCard c={{ ...BASE, status: "APPROVED" }}
      onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.queryByText("批准")).toBeNull();
  });
});
