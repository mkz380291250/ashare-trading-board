import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RoleStages } from "./RoleStages";

const ROLES = [
  { role: "量价分析师", stage: "analyst", stance: "bull", action: null, confidence: 0.7, text: "放量突破" },
  { role: "多头研究员", stage: "debate", stance: "bull", action: null, confidence: 0.6, text: "买入" },
  { role: "空头研究员", stage: "debate", stance: "bear", action: null, confidence: 0.5, text: "风险" },
  { role: "风控经理", stage: "verdict", stance: null, action: "HOLD", confidence: 0.62, text: "观望" },
];

describe("RoleStages", () => {
  it("renders stage groups and role text", () => {
    render(<RoleStages roles={ROLES} />);
    expect(screen.getByText("分析师团")).toBeInTheDocument();
    expect(screen.getByText("多空辩论")).toBeInTheDocument();
    expect(screen.getByText("风控经理裁决")).toBeInTheDocument();
    expect(screen.getByText("放量突破")).toBeInTheDocument();
    expect(screen.getAllByText("多").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("空")).toBeInTheDocument();
  });

  it("omits empty stages", () => {
    render(<RoleStages roles={[ROLES[0]]} />);
    expect(screen.queryByText("风控团")).toBeNull();
  });
});
