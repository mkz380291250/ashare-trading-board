import { Typography } from "antd";
import { RoleCard, type Role } from "./RoleCard";

export type { Role };

const STAGES = [
  { key: "analyst", label: "分析师团" },
  { key: "debate", label: "多空辩论" },
  { key: "trader", label: "交易员草案" },
  { key: "risk", label: "风控团" },
  { key: "verdict", label: "风控经理裁决" },
];

export function RoleStages({ roles }: { roles: Role[] }) {
  return (
    <div>
      {STAGES.map((st) => {
        const items = roles.filter((r) => r.stage === st.key);
        if (!items.length) return null;
        return (
          <div key={st.key} data-testid={`stage-${st.key}`} style={{ marginTop: 16 }}>
            <Typography.Title level={5}
              style={st.key === "verdict" ? { color: "#d4380d" } : undefined}>
              {st.label}
            </Typography.Title>
            {items.map((r, i) => <RoleCard key={`${r.role}-${i}`} r={r} />)}
          </div>
        );
      })}
    </div>
  );
}
