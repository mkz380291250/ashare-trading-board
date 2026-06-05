import { Card, Space, Tag } from "antd";
import { ResponsiveList } from "./ResponsiveList";
import { semanticColor } from "../theme/tokens";

type Position = {
  code: string;
  shares: number;
  cost: number;
  name?: string | null;
  buy_date?: string | null;
  last_close?: number | null;
  market_value?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
};

export function PositionsTable({
  positions,
  forceMobile,
}: {
  positions: Position[];
  forceMobile?: boolean;
}) {
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "名称", dataIndex: "name", key: "name",
      render: (v: string | null) => v ?? "—" },
    { title: "股数", dataIndex: "shares", key: "shares" },
    { title: "成本", dataIndex: "cost", key: "cost",
      render: (v: number) => v.toFixed(2) },
    { title: "买入时间", dataIndex: "buy_date", key: "buy_date",
      render: (v: string | null) => v ?? "—" },
    { title: "现价", dataIndex: "last_close", key: "last_close",
      render: (v: number | null) => v == null ? "—" : v.toFixed(2) },
    { title: "市值", dataIndex: "market_value", key: "market_value",
      render: (v: number | null) => v == null ? "—" : v.toFixed(0) },
    {
      title: "盈亏",
      dataIndex: "pnl",
      key: "pnl",
      render: (_v: number | null, record: Position) => {
        const { pnl, pnl_pct } = record;
        if (pnl == null) return "—";
        const sign = pnl >= 0 ? "+" : "";
        const pct = ((pnl_pct ?? 0) * 100).toFixed(1);
        return (
          <span style={{ color: semanticColor(pnl) }}>
            {sign}{pnl.toFixed(0)} ({sign}{pct}%)
          </span>
        );
      },
    },
  ];

  return (
    <ResponsiveList
      dataSource={positions}
      columns={columns}
      rowKey="code"
      forceMobile={forceMobile}
      renderCard={(p) => {
        const pnlText = p.pnl == null ? "—"
          : `${p.pnl >= 0 ? "+" : ""}${p.pnl.toFixed(0)} (${((p.pnl_pct ?? 0) * 100).toFixed(1)}%)`;
        return (
          <Card size="small">
            <Space split="·"><b>{p.name || p.code}</b><span>{p.code}</span></Space>
            <div style={{ marginTop: 6 }}>
              <Tag>股数 {p.shares}</Tag><Tag>成本 {p.cost}</Tag>
              {p.buy_date && <Tag>买入 {p.buy_date}</Tag>}
              <Tag color={semanticColor(p.pnl)}>{pnlText}</Tag>
            </div>
          </Card>
        );
      }}
    />
  );
}
