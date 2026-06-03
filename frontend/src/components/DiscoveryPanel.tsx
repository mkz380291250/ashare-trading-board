import { useEffect, useState } from "react";
import { Table, Empty } from "antd";
import { apiGet } from "../api/client";

type Pick = { as_of: string; code: string; rank: number; score: number;
  factors: Record<string, number> };

export function DiscoveryPanel() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/discovery").then(setPicks).catch(() => {});
  }, []);
  if (!picks.length) return <Empty description="机会榜暂无数据" />;
  const columns = [
    { title: "#", dataIndex: "rank", key: "rank" },
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "评分", dataIndex: "score", key: "score",
      render: (v: number) => v.toFixed(3) },
    { title: "因子", dataIndex: "factors", key: "factors",
      render: (f: Record<string, number>) =>
        Object.entries(f).map(([k, v]) => `${k}:${v.toFixed(2)}`).join("  ") },
  ];
  return <Table rowKey="code" size="small" pagination={false}
                dataSource={picks} columns={columns} />;
}
