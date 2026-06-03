import { Table, Tag, Empty } from "antd";

type Pick = {
  code: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

const pct = (v: number | null) => v == null ? "-" : `${(v * 100).toFixed(1)}%`;

export function PicksTable({ picks }: { picks: Pick[] }) {
  if (!picks.length) return <Empty description="选股池暂无数据" />;
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "题材", dataIndex: "theme", key: "theme",
      render: (t: string) => <Tag color="blue">{t}</Tag> },
    { title: "入选日", dataIndex: "first_selected_on", key: "d" },
    { title: "入选价", dataIndex: "entry_close", key: "p",
      render: (v: number) => v.toFixed(2) },
    { title: "T+1", dataIndex: "ret_t1", key: "t1", render: pct },
    { title: "T+3", dataIndex: "ret_t3", key: "t3", render: pct },
    { title: "T+5", dataIndex: "ret_t5", key: "t5", render: pct },
    { title: "T+10", dataIndex: "ret_t10", key: "t10", render: pct },
  ];
  return <Table rowKey={(r) => `${r.code}-${r.first_selected_on}`} size="small"
                pagination={false} dataSource={picks} columns={columns} />;
}
