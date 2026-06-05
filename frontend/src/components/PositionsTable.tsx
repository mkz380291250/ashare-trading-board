import { Card, Space } from "antd";
import { ResponsiveList } from "./ResponsiveList";

type Position = { code: string; shares: number; cost: number };

export function PositionsTable({
  positions,
  forceMobile,
}: {
  positions: Position[];
  forceMobile?: boolean;
}) {
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "股数", dataIndex: "shares", key: "shares" },
    { title: "成本", dataIndex: "cost", key: "cost",
      render: (v: number) => v.toFixed(2) },
  ];
  return (
    <ResponsiveList
      dataSource={positions}
      columns={columns}
      rowKey="code"
      forceMobile={forceMobile}
      renderCard={(p) => (
        <Card size="small">
          <Space split="·">
            <b>{p.code}</b>
            <span>股数 {p.shares}</span>
            <span>成本 {p.cost}</span>
          </Space>
        </Card>
      )}
    />
  );
}
