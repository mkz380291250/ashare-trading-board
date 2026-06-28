// frontend/src/components/HealthPanel.tsx
import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col } from "antd";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../api/client";

type HitRate = { window: number; hit_rate: number | null; n: number };
type ICPoint = { rank_ic: number | null };
type Action = { kind: string; as_of: string; detail: string };
type Eq = { drawdown: number };

export function HealthPanel({ accountId }: { accountId: number }) {
  const [hr, setHr] = useState<HitRate | null>(null);
  const [ric, setRic] = useState<number | null>(null);
  const [dd, setDd] = useState<number | null>(null);
  const [actions, setActions] = useState<Action[]>([]);
  const nav = useNavigate();
  useEffect(() => {
    apiGet<HitRate>("/api/attribution/hit-rate?window=30").then(setHr).catch(() => {});
    apiGet<ICPoint[]>("/api/attribution/forward-ic?days=60")
      .then((s) => setRic(s.length ? s[s.length - 1].rank_ic : null)).catch(() => {});
    apiGet<Eq[]>(`/api/equity/${accountId}`)
      .then((e) => setDd(e.length ? e[e.length - 1].drawdown : null)).catch(() => {});
    apiGet<Action[]>("/api/policy/actions?limit=50").then(setActions).catch(() => {});
  }, [accountId]);
  const today = actions[0]?.as_of;
  const todayCount = actions.filter((a) => a.as_of === today).length;
  const ddRed = dd != null && dd < -0.2;
  const hrRed = hr?.hit_rate != null && hr.hit_rate < 0.4;
  return (
    <Card title="闭环健康" style={{ marginBottom: 16 }}>
      <Row gutter={16}>
        <Col xs={12} sm={6}><Statistic title="近30日胜率"
          value={hr?.hit_rate != null ? hr.hit_rate * 100 : NaN} precision={0} suffix="%"
          valueStyle={hrRed ? { color: "#cf1322" } : undefined} /></Col>
        <Col xs={12} sm={6}><Statistic title="滚动RankIC"
          value={ric != null ? ric : NaN} precision={4} /></Col>
        <Col xs={12} sm={6}><Statistic title="当前回撤"
          value={dd != null ? dd * 100 : NaN} precision={1} suffix="%"
          valueStyle={ddRed ? { color: "#cf1322" } : undefined} /></Col>
        <Col xs={12} sm={6}><Statistic title="今日策略动作" value={todayCount} /></Col>
      </Row>
      {actions[0] && (
        <div style={{ marginTop: 8, cursor: "pointer", color: "#1677ff" }}
          onClick={() => nav("/policy")}>
          最近:{actions[0].as_of} {actions[0].kind} — {actions[0].detail}
        </div>
      )}
    </Card>
  );
}
