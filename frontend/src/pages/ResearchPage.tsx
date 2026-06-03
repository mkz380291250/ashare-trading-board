import { useEffect, useState } from "react";
import { Row, Col, Card, Table, Statistic, Tag, Empty, Typography } from "antd";
import { apiGet } from "../api/client";

type Note = { code: string; as_of: string; sentiment: number;
  rating_consensus: string; summary: string };

export function ResearchPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [sel, setSel] = useState<Note | null>(null);
  useEffect(() => {
    apiGet<Note[]>("/api/research").then((n) => {
      setNotes(n); setSel(n[0] ?? null);
    }).catch(() => {});
  }, []);

  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "情绪", dataIndex: "sentiment", key: "s",
      render: (v: number) => <Tag color={v > 0.1 ? "red" : v < -0.1 ? "green" : "default"}>
        {v.toFixed(2)}</Tag> },
    { title: "日期", dataIndex: "as_of", key: "d" },
  ];
  return (
    <Row gutter={16}>
      <Col span={10}>
        <Card title="研报覆盖个股">
          {notes.length ? (
            <Table rowKey="code" size="small" pagination={false} dataSource={notes}
              columns={columns}
              onRow={(r) => ({ onClick: () => setSel(r), style: { cursor: "pointer" } })} />
          ) : <Empty description="暂无研报,先跑 run_research.py" />}
        </Card>
      </Col>
      <Col span={14}>
        {sel ? (
          <Card title={`${sel.code} 研报观点(${sel.as_of})`}>
            <Statistic title="情绪分(-1~1)" value={sel.sentiment} precision={2} />
            <p style={{ marginTop: 12 }}><b>评级共识:</b>{sel.rating_consensus || "—"}</p>
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              {sel.summary}</Typography.Paragraph>
          </Card>
        ) : <Empty description="选择左侧个股查看研报" />}
      </Col>
    </Row>
  );
}
