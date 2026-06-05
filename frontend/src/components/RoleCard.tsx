import { Card, Tag } from "antd";

export type Role = {
  role: string; stage: string; stance: string | null;
  action: string | null; confidence: number | null; text: string;
};

const LABEL: Record<string, { t: string; c: string }> = {
  bull: { t: "多", c: "red" },
  bear: { t: "空", c: "green" },
  neutral: { t: "中", c: "default" },
  aggressive: { t: "激进", c: "volcano" },
  conservative: { t: "保守", c: "blue" },
  BUY: { t: "BUY", c: "red" },
  SELL: { t: "SELL", c: "green" },
  HOLD: { t: "HOLD", c: "default" },
};

export function RoleCard({ r }: { r: Role }) {
  const tag = LABEL[r.action ?? r.stance ?? ""];
  return (
    <Card size="small" style={{ marginBottom: 8 }} title={
      <span>
        {r.role}
        {tag && <Tag color={tag.c} style={{ marginLeft: 8 }}>{tag.t}</Tag>}
        {r.confidence != null && (
          <span style={{ fontWeight: 400, marginLeft: 8 }}>信心 {r.confidence.toFixed(2)}</span>
        )}
      </span>
    }>
      <div style={{ whiteSpace: "pre-wrap" }}>{r.text}</div>
    </Card>
  );
}
