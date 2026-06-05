import { useCallback, useEffect, useState } from "react";
import { Row, Col, Card, Statistic, Spin } from "antd";
import { apiGet } from "../api/client";
import { PositionsTable } from "../components/PositionsTable";
import { EquityChart } from "../components/EquityChart";
import { TradeForm } from "../components/TradeForm";
import { DiscoveryPanel } from "../components/DiscoveryPanel";
import { DecisionsPanel } from "../components/DecisionsPanel";

type Account = { id: number; name: string; cash: number;
  positions: { code: string; shares: number; cost: number }[] };
type Equity = { as_of: string; total: number }[];

const ACCOUNT_ID = 1;

export function Dashboard() {
  const [acc, setAcc] = useState<Account | null>(null);
  const [eq, setEq] = useState<Equity>([]);
  const load = useCallback(() => {
    apiGet<Account>(`/api/account/${ACCOUNT_ID}`).then(setAcc).catch(() => {});
    apiGet<Equity>(`/api/equity/${ACCOUNT_ID}`).then(setEq).catch(() => {});
  }, []);
  useEffect(load, [load]);

  if (!acc) return <Spin />;
  const mv = acc.positions.reduce((s, p) => s + p.shares * p.cost, 0);
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Row gutter={16}>
        <Col xs={24} sm={8}><Card><Statistic title="现金" value={acc.cash} precision={2} /></Card></Col>
        <Col xs={24} sm={8}><Card><Statistic title="持仓成本市值" value={mv} precision={2} /></Card></Col>
        <Col xs={24} sm={8}><Card><Statistic title="总(现金+持仓)" value={acc.cash + mv} precision={2} /></Card></Col>
      </Row>
      <Card title="下单(人机协同)"><TradeForm accountId={ACCOUNT_ID} onDone={load} /></Card>
      <Card title="持仓"><PositionsTable positions={acc.positions} /></Card>
      <Card title="净值曲线"><EquityChart points={eq} /></Card>
      <Card title="机会榜 Top-8"><DiscoveryPanel /></Card>
      <Card title="决策(人机协同)"><DecisionsPanel /></Card>
    </div>
  );
}
