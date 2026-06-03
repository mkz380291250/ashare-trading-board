import { Table, Empty, Button } from "antd";

export type Track = {
  code: string; name: string; added_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
  last_close: number | null; ret_since: number | null;
  max_gain: number | null; max_drawdown: number | null;
  last_updated: string | null;
};

const pct = (v: number | null) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null) => (v == null ? "-" : v.toFixed(2));

export function TrackTable(
  { rows, onRemove }: { rows: Track[]; onRemove: (code: string, on: string) => void },
) {
  if (!rows.length) return <Empty description="暂无跟踪标的" />;
  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "名称", dataIndex: "name", key: "name" },
    { title: "入选日", dataIndex: "added_on", key: "d" },
    { title: "入选价", dataIndex: "entry_close", key: "ep", render: num },
    { title: "最新", dataIndex: "last_close", key: "lc", render: num },
    { title: "至今", dataIndex: "ret_since", key: "rs", render: pct },
    { title: "T+1", dataIndex: "ret_t1", key: "t1", render: pct },
    { title: "T+3", dataIndex: "ret_t3", key: "t3", render: pct },
    { title: "T+5", dataIndex: "ret_t5", key: "t5", render: pct },
    { title: "T+10", dataIndex: "ret_t10", key: "t10", render: pct },
    { title: "最大涨幅", dataIndex: "max_gain", key: "mg", render: pct },
    { title: "最大回撤", dataIndex: "max_drawdown", key: "md", render: pct },
    { title: "更新日", dataIndex: "last_updated", key: "u",
      render: (v: string | null) => v ?? "-" },
    { title: "操作", key: "op",
      render: (_: unknown, r: Track) => (
        <Button size="small" danger onClick={() => onRemove(r.code, r.added_on)}>
          删除
        </Button>
      ) },
  ];
  return <Table rowKey={(r) => `${r.code}-${r.added_on}`} size="small"
                pagination={false} dataSource={rows} columns={columns}
                scroll={{ x: true }} />;
}
