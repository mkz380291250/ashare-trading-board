import { Table } from "antd";

type Position = { code: string; shares: number; cost: number };

export function PositionsTable({ positions }: { positions: Position[] }) {
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "股数", dataIndex: "shares", key: "shares" },
    { title: "成本", dataIndex: "cost", key: "cost",
      render: (v: number) => v.toFixed(2) },
  ];
  return <Table rowKey="code" size="small" pagination={false}
                dataSource={positions} columns={columns} />;
}
