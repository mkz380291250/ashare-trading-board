import { useEffect, useState, useCallback } from "react";
import { Row, Col, Card, Table, Tag, Empty } from "antd";
import { apiGet, apiPost } from "../api/client";
import { ConclusionCard, type Conclusion } from "../components/ConclusionCard";
import { RoleStages } from "../components/RoleStages";
import type { Role } from "../components/RoleCard";

type ListItem = { id: number; code: string; action: string; status: string };
type Detail = Conclusion & { roles: Role[] };

const ACTION_COLOR: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };

export function DecisionsPage() {
  const [rows, setRows] = useState<ListItem[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);

  const loadList = useCallback(() => {
    apiGet<ListItem[]>("/api/decisions").then((r) => {
      setRows(r);
      setSel((cur) => (cur == null && r[0] ? r[0].id : cur));
    }).catch(() => {});
  }, []);
  useEffect(() => { loadList(); }, [loadList]);

  const loadDetail = useCallback((id: number) => {
    apiGet<Detail>(`/api/decisions/${id}`).then(setDetail).catch(() => {});
  }, []);
  useEffect(() => { if (sel != null) loadDetail(sel); }, [sel, loadDetail]);

  async function act(what: "approve" | "reject", price = 0) {
    if (sel == null) return;
    await apiPost(`/api/decisions/${sel}/${what}`, what === "approve" ? { price } : {});
    loadList(); loadDetail(sel);
  }

  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "动作", dataIndex: "action", key: "action",
      render: (a: string) => <Tag color={ACTION_COLOR[a] || "default"}>{a}</Tag> },
    { title: "状态", dataIndex: "status", key: "status" },
  ];

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card title="决策列表">
          {rows.length ? (
            <Table rowKey="id" size="small" pagination={false} dataSource={rows}
              columns={columns}
              onRow={(r) => ({ onClick: () => setSel(r.id), style: { cursor: "pointer" } })} />
          ) : <Empty description="暂无决策,先跑 run_decisions.py" />}
        </Card>
      </Col>
      <Col span={16}>
        {detail ? (
          <>
            <ConclusionCard c={detail}
              onApprove={(p) => act("approve", p)} onReject={() => act("reject")} />
            <RoleStages roles={detail.roles} />
          </>
        ) : <Empty description="选择左侧决策查看辩论" />}
      </Col>
    </Row>
  );
}
