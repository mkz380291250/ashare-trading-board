import { useEffect, useState } from "react";
import { Card, Table, Tag } from "antd";
import { apiGet } from "../api/client";

type Action = { id: number; kind: string; as_of: string; trigger: string;
                detail: string; status: string };

const KIND_COLOR: Record<string, string> = {
  REMINE: "blue", RISK_OFF: "orange", WEAK_SELL: "red",
};
const STATUS_COLOR: Record<string, string> = {
  AUTO: "green", PENDING: "default", FAILED: "red",
};

export function PolicyPage() {
  const [rows, setRows] = useState<Action[]>([]);
  useEffect(() => {
    apiGet<Action[]>("/api/policy/actions?limit=50").then(setRows).catch(() => {});
  }, []);
  const columns = [
    { title: "时间", dataIndex: "as_of", key: "as_of" },
    { title: "类型", dataIndex: "kind", key: "kind",
      render: (k: string) => <Tag color={KIND_COLOR[k] || "default"}>{k}</Tag> },
    { title: "触发", dataIndex: "trigger", key: "trigger" },
    { title: "说明", dataIndex: "detail", key: "detail" },
    { title: "状态", dataIndex: "status", key: "status",
      render: (st: string) => <Tag color={STATUS_COLOR[st] || "default"}>{st}</Tag> },
  ];
  return (
    <div>
      <h2>策略闸</h2>
      <Card>
        <Table rowKey="id" dataSource={rows} columns={columns} size="small"
          locale={{ emptyText: "暂无策略动作" }} pagination={false} />
      </Card>
    </div>
  );
}
