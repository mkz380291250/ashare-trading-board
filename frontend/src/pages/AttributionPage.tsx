import { useEffect, useState } from "react";
import { Card, Statistic, Row, Col } from "antd";
import { apiGet } from "../api/client";
import { ForwardICChart } from "../components/ForwardICChart";

type HitRate = { window: number; hit_rate: number | null; n: number };
type ICPoint = { as_of: string; ic: number | null; rank_ic: number | null; n: number };

export function AttributionPage() {
  const [hr, setHr] = useState<HitRate | null>(null);
  const [ic, setIc] = useState<ICPoint[]>([]);
  useEffect(() => {
    apiGet<HitRate>("/api/attribution/hit-rate?window=30").then(setHr).catch(() => {});
    apiGet<ICPoint[]>("/api/attribution/forward-ic?days=60").then(setIc).catch(() => {});
  }, []);
  return (
    <div>
      <h2>归因</h2>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12}><Card><Statistic title="近30日胜率"
          value={hr?.hit_rate != null ? hr.hit_rate * 100 : NaN}
          precision={0} suffix="%" /></Card></Col>
        <Col xs={12}><Card><Statistic title="样本数" value={hr?.n ?? 0} /></Card></Col>
      </Row>
      <Card title="复合因子前向 IC / RankIC"><ForwardICChart points={ic} /></Card>
    </div>
  );
}
