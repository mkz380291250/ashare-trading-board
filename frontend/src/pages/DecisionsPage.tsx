import { useEffect, useState, useCallback } from "react";
import { Row, Col, Card, Tag, Empty, Space, Input, Button } from "antd";
import { apiGet, apiPost } from "../api/client";
import { ConclusionCard, type Conclusion } from "../components/ConclusionCard";
import { RoleStages } from "../components/RoleStages";
import { ManualTrade } from "../components/ManualTrade";
import type { Role } from "../components/RoleCard";
import { ResponsiveList } from "../components/ResponsiveList";
import { StockLink } from "../components/StockLink";

type ListItem = { id: number; code: string; name?: string; action: string; status: string };
type Detail = Conclusion & { roles: Role[] };
type Job = { id: number; code: string; status: string; decision_id: number | null };

const ACTION_COLOR: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };

export function DecisionsPage() {
  const [rows, setRows] = useState<ListItem[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [code, setCode] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);

  const loadList = useCallback(() => {
    apiGet<ListItem[]>("/api/decisions").then((r) => {
      setRows(r);
      setSel((cur) => (cur == null && r[0] ? r[0].id : cur));
    }).catch(() => {});
  }, []);
  useEffect(() => { loadList(); }, [loadList]);

  const loadJobs = useCallback(() => {
    apiGet<Job[]>("/api/decisions/jobs").then(setJobs).catch(() => {});
  }, []);
  useEffect(() => {
    loadJobs();
    const t = setInterval(loadJobs, 5000);
    return () => clearInterval(t);
  }, [loadJobs]);

  const loadDetail = useCallback((id: number) => {
    apiGet<Detail>(`/api/decisions/${id}`).then(setDetail).catch(() => {});
  }, []);
  useEffect(() => { if (sel != null) loadDetail(sel); }, [sel, loadDetail]);

  async function act(what: "approve" | "reject", price = 0) {
    if (sel == null) return;
    await apiPost(`/api/decisions/${sel}/${what}`, what === "approve" ? { price } : {});
    loadList(); loadDetail(sel);
  }

  const submit = async () => {
    const c = code.trim();
    if (!c) return;
    await apiPost("/api/decisions/run", { code: c });
    setCode("");
    loadJobs();
    loadList();
  };

  const columns = [
    { title: "代码", dataIndex: "code", key: "code",
      render: (_: string, r: ListItem) => <StockLink code={r.code} name={r.name} /> },
    { title: "动作", dataIndex: "action", key: "action",
      render: (a: string) => <Tag color={ACTION_COLOR[a] || "default"}>{a}</Tag> },
    { title: "状态", dataIndex: "status", key: "status" },
  ];

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Input
          placeholder="输入股票代号"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          style={{ width: 160 }}
        />
        <Button type="primary" onClick={submit}>开始辩论</Button>
      </Space>
      <Space style={{ marginBottom: 12 }}>
        {jobs.filter(j => j.status === "PENDING" || j.status === "RUNNING").map(j => (
          <Tag key={j.id}>{j.code} {j.status}</Tag>
        ))}
      </Space>
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card title="决策列表">
            <ResponsiveList<ListItem>
              dataSource={rows}
              columns={columns}
              rowKey="id"
              onRowClick={(r) => setSel(r.id)}
              empty={<Empty description="暂无决策,先跑 run_decisions.py" />}
              renderCard={(r) => (
                <Card size="small"><Space split="·">
                  <b><StockLink code={r.code} name={r.name} /></b>
                  <Tag color={ACTION_COLOR[r.action] || "default"}>{r.action}</Tag>
                  <span>{r.status}</span>
                </Space></Card>
              )}
            />
          </Card>
        </Col>
        <Col xs={24} md={16}>
          {detail ? (
            <>
              <ConclusionCard c={detail}
                onApprove={(p) => act("approve", p)} onReject={() => act("reject")} />
              <RoleStages roles={detail.roles} />
              <ManualTrade code={detail.code} onDone={() => loadDetail(detail.id)} />
            </>
          ) : <Empty description="选择左侧决策查看辩论" />}
        </Col>
      </Row>
    </>
  );
}
