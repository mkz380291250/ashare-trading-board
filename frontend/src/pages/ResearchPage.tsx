import { useEffect, useState } from "react";
import { Row, Col, Card, Space, Statistic, Tag, Empty, Typography } from "antd";
import { apiGet } from "../api/client";
import { ResponsiveList } from "../components/ResponsiveList";
import { semanticColor } from "../theme/tokens";

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
      render: (v: number) => <Tag color={semanticColor(v)}>{v.toFixed(2)}</Tag> },
    { title: "日期", dataIndex: "as_of", key: "d" },
  ];
  return (
    <Row gutter={16}>
      <Col xs={24} md={10}>
        <Card title="研报覆盖个股">
          <ResponsiveList<Note>
            dataSource={notes}
            columns={columns}
            rowKey="code"
            onRowClick={(r) => setSel(r)}
            empty={<Empty description="暂无研报,先跑 run_research.py" />}
            renderCard={(n) => (
              <Card size="small">
                <Space split="·">
                  <b>{n.code}</b>
                  <Tag color={semanticColor(n.sentiment)}>{n.sentiment.toFixed(2)}</Tag>
                  <span>{n.as_of}</span>
                </Space>
              </Card>
            )}
          />
        </Card>
      </Col>
      <Col xs={24} md={14}>
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
