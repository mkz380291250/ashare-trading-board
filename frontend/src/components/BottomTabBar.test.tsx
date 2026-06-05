import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { BottomTabBar } from "./BottomTabBar";

describe("BottomTabBar", () => {
  it("renders the 5 primary tabs + 更多", () => {
    render(<MemoryRouter><BottomTabBar onMore={vi.fn()} /></MemoryRouter>);
    ["看板", "选股", "跟踪", "决策", "更多"].forEach((t) =>
      expect(screen.getByText(t)).toBeInTheDocument());
  });

  it("calls onMore when 更多 tapped", () => {
    const onMore = vi.fn();
    render(<MemoryRouter><BottomTabBar onMore={onMore} /></MemoryRouter>);
    fireEvent.click(screen.getByText("更多"));
    expect(onMore).toHaveBeenCalled();
  });
});
