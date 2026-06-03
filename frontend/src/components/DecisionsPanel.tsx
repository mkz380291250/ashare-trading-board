import { useCallback, useEffect, useState } from "react";
import { Table, Tag, Button, Space, Empty, Typography } from "antd";
import { apiGet, apiPost } from "../api/client";

type Decision = { id: number; code: string; action: string; confidence: number;
  shares: number; status: string; reasoning: string };

export function DecisionsPanel() {
  const [rows, setRows] = useState<Decision[]>([]);
  const load = useCallback(() => {
    apiGet<Decision[]>("/api/decisions").then(setRows).catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function act(id: number, what: "approve" | "reject") {
    await apiPost(`/api/decisions/${id}/${what}`, what === "approve" ? { price: 0 } : {});
    load();
  }
  if (!rows.length) return <Empty description="暂无决策" />;
  const color: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "动作", dataIndex: "action", key: "action",
      render: (a: string) => <Tag color={color[a] || "default"}>{a}</Tag> },
    { title: "信心", dataIndex: "confidence", key: "confidence",
      render: (v: number) => v.toFixed(2) },
    { title: "股数", dataIndex: "shares", key: "shares" },
    { title: "状态", dataIndex: "status", key: "status" },
    { title: "操作", key: "act", render: (_: unknown, d: Decision) =>
        d.status === "PENDING" ? (
          <Space>
            <Button size="small" type="primary" onClick={() => act(d.id, "approve")}>批准</Button>
            <Button size="small" danger onClick={() => act(d.id, "reject")}>驳回</Button>
          </Space>) : null },
  ];
  return (
    <Table rowKey="id" size="small" pagination={false} dataSource={rows} columns={columns}
      expandable={{ expandedRowRender: (d) =>
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>
          {d.reasoning}</Typography.Paragraph> }} />
  );
}
