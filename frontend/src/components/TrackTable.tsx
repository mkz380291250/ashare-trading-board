import { Empty, Button, Tag, Card, Space } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ResponsiveList } from "./ResponsiveList";
import { StockLink } from "./StockLink";
import { semanticColor } from "../theme/tokens";

export type Track = {
  code: string; name: string; added_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
  last_close: number | null; ret_since: number | null;
  max_gain: number | null; max_drawdown: number | null;
  signal: string; buy_price: number | null; buy_return: number | null;
  last_updated: string | null;
};

const pct = (v: number | null) => (v == null ? "-" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null) => (v == null ? "-" : v.toFixed(2));

export function TrackTable(
  { rows, onRemove, forceMobile }: {
    rows: Track[];
    onRemove: (code: string, on: string) => void;
    forceMobile?: boolean;
  },
) {
  if (!rows.length) return <Empty description="暂无跟踪标的" />;
  const columns: ColumnsType<Track> = [
    { title: "信号", dataIndex: "signal", key: "sig", width: 64, fixed: "left",
      render: (v: string) => (v === "buy" ? <Tag color="red">买入</Tag> : "-") },
    { title: "代码", dataIndex: "code", key: "code", width: 96, fixed: "left",
      render: (_: string, r: Track) => (
        <StockLink code={r.code} name={r.name}>{r.code}</StockLink>) },
    { title: "名称", dataIndex: "name", key: "name", width: 96, fixed: "left",
      onCell: () => ({ style: { whiteSpace: "nowrap" } }) },
    { title: "入选日", dataIndex: "added_on", key: "d", width: 104 },
    { title: "入选价", dataIndex: "entry_close", key: "ep", width: 80, render: num },
    { title: "买入价", dataIndex: "buy_price", key: "bp", width: 80, render: num },
    { title: "买入收益", dataIndex: "buy_return", key: "br", width: 88, render: pct },
    { title: "最新", dataIndex: "last_close", key: "lc", width: 80, render: num },
    { title: "至今", dataIndex: "ret_since", key: "rs", width: 72, render: pct },
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
  return (
    <ResponsiveList<Track>
      dataSource={rows}
      columns={columns}
      rowKey={(r) => `${r.code}-${r.added_on}`}
      forceMobile={forceMobile}
      empty={<Empty description="暂无跟踪标的" />}
      renderCard={(r) => (
        <Card size="small" extra={<a onClick={() => onRemove(r.code, r.added_on)}>移除</a>}>
          <Space split="·">
            <b><StockLink code={r.code} name={r.name}>{r.name || r.code}</StockLink></b><span>{r.code}</span>
            {r.signal === "buy" && <Tag color="red">buy@{r.buy_price}</Tag>}
          </Space>
          <div style={{ marginTop: 6 }}>
            <Tag color={semanticColor(r.ret_since)}>至今 {((r.ret_since ?? 0) * 100).toFixed(1)}%</Tag>
            <Tag color={semanticColor(r.max_gain)}>最大涨 {((r.max_gain ?? 0) * 100).toFixed(1)}%</Tag>
            <Tag color={semanticColor(r.max_drawdown)}>最大回 {((r.max_drawdown ?? 0) * 100).toFixed(1)}%</Tag>
          </div>
        </Card>
      )}
    />
  );
}
