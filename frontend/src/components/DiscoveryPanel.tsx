import { useEffect, useState } from "react";
import { Empty, Card, Space, Tag } from "antd";
import { apiGet } from "../api/client";
import { ResponsiveList } from "./ResponsiveList";
import { StockLink } from "./StockLink";
import { semanticColor } from "../theme/tokens";

type Pick = { as_of: string; code: string; name?: string; rank: number; score: number;
  factors: Record<string, number> };

export function DiscoveryPanel() {
  const [picks, setPicks] = useState<Pick[]>([]);
  useEffect(() => {
    apiGet<Pick[]>("/api/discovery").then(setPicks).catch(() => {});
  }, []);
  if (!picks.length) return <Empty description="机会榜暂无数据" />;
  const columns = [
    { title: "#", dataIndex: "rank", key: "rank" },
    { title: "代码", dataIndex: "code", key: "code",
      render: (_: string, p: Pick) => <StockLink code={p.code} name={p.name} /> },
    { title: "评分", dataIndex: "score", key: "score",
      render: (v: number) => v.toFixed(3) },
    { title: "因子", dataIndex: "factors", key: "factors",
      render: (f: Record<string, number>) =>
        Object.entries(f).map(([k, v]) => `${k}:${v.toFixed(2)}`).join("  ") },
  ];
  return (
    <ResponsiveList
      dataSource={picks}
      columns={columns}
      rowKey="code"
      renderCard={(p) => (
        <Card size="small">
          <Space split="·">
            <b>{p.rank}. <StockLink code={p.code} name={p.name} /></b>
            <Tag color={semanticColor(p.score - 0.5)}>
              评分 {p.score.toFixed(3)}
            </Tag>
            <span style={{ fontSize: 12, color: "#888" }}>
              {Object.entries(p.factors)
                .map(([k, v]) => `${k}:${v.toFixed(2)}`)
                .join("  ")}
            </span>
          </Space>
        </Card>
      )}
    />
  );
}
