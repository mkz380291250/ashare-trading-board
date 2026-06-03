import { useCallback, useEffect, useState } from "react";
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

  if (!acc) return <p>加载中…</p>;
  return (
    <div style={{ padding: 24, display: "grid", gap: 16 }}>
      <h1>{acc.name} 模拟账户</h1>
      <p>现金: {acc.cash.toFixed(2)}</p>
      <TradeForm accountId={ACCOUNT_ID} onDone={load} />
      <h2>持仓</h2>
      <PositionsTable positions={acc.positions} />
      <h2>净值曲线</h2>
      <EquityChart points={eq} />
      <h2>机会榜 Top-8</h2>
      <DiscoveryPanel />
      <h2>决策(人机协同)</h2>
      <DecisionsPanel />
    </div>
  );
}
