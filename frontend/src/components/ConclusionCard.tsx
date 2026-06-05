import { useState } from "react";
import { Card, Tag, Statistic, Row, Col, Button, Space, InputNumber } from "antd";

export type Conclusion = {
  id: number; code: string; name: string | null; action: string;
  confidence: number; shares: number; status: string; summary: string;
};

const ACTION_COLOR: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };

export function ConclusionCard({ c, onApprove, onReject }: {
  c: Conclusion; onApprove: (price: number) => void; onReject: () => void;
}) {
  const [price, setPrice] = useState(0);
  return (
    <Card style={{ marginBottom: 16 }}>
      <Row align="middle" gutter={16}>
        <Col flex="auto">
          <Tag color={ACTION_COLOR[c.action] || "default"}
            style={{ fontSize: 28, padding: "4px 16px", lineHeight: "40px" }}>
            {c.action}
          </Tag>
          <span style={{ fontSize: 18, marginLeft: 12 }}>{c.code} {c.name ?? ""}</span>
          <div style={{ marginTop: 8 }}>{c.summary}</div>
        </Col>
        <Col><Statistic title="信心" value={c.confidence} precision={2} /></Col>
        <Col><Statistic title="建议股数" value={c.shares} /></Col>
        {c.status === "PENDING" && (
          <Col>
            <Space>
              <InputNumber placeholder="成交价" value={price}
                onChange={(v) => setPrice(v ?? 0)} />
              <Button type="primary" autoInsertSpace={false} onClick={() => onApprove(price)}>批准</Button>
              <Button danger autoInsertSpace={false} onClick={onReject}>驳回</Button>
            </Space>
          </Col>
        )}
        {c.status !== "PENDING" && (
          <Col>
            <span style={{ color: "#13c281" }}>✅ 已自动执行({c.action})</span>
          </Col>
        )}
      </Row>
    </Card>
  );
}
