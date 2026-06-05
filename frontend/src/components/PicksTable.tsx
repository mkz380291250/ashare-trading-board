import { Tag, Empty, Card, Space } from "antd";
import { ResponsiveList } from "./ResponsiveList";
import { semanticColor } from "../theme/tokens";

type Pick = {
  code: string; name?: string; theme: string; first_selected_on: string; entry_close: number;
  ret_t1: number | null; ret_t3: number | null;
  ret_t5: number | null; ret_t10: number | null;
};

const pct = (v: number | null) => v == null ? "-" : `${(v * 100).toFixed(1)}%`;

const columns = [
  { title: "代码", dataIndex: "code", key: "code",
    render: (_: string, p: Pick) => p.name ? `${p.name}(${p.code})` : p.code },
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

export function PicksTable({ picks, forceMobile }: { picks: Pick[]; forceMobile?: boolean }) {
  return (
    <ResponsiveList<Pick>
      dataSource={picks}
      columns={columns}
      rowKey={(r) => `${r.code}-${r.first_selected_on}`}
      forceMobile={forceMobile}
      empty={<Empty description="暂无选股,先跑 run_screener.py" />}
      renderCard={(p) => (
        <Card size="small">
          <Space split="·">
            <b>{p.name ? `${p.name}(${p.code})` : p.code}</b><Tag>{p.theme}</Tag><span>{p.first_selected_on}</span>
          </Space>
          <div style={{ marginTop: 6 }}>
            {(["ret_t1", "ret_t3", "ret_t5", "ret_t10"] as const).map((k) => (
              <Tag key={k} color={semanticColor(p[k])}>
                {k.replace("ret_t", "T+")} {p[k] == null ? "—" : (p[k]! * 100).toFixed(1) + "%"}
              </Tag>
            ))}
          </div>
        </Card>
      )}
    />
  );
}
