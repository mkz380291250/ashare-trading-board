import { useEffect, useState } from "react";
import { Card, Input, Button, message, Space } from "antd";
import { apiGet, apiPost, apiDelete } from "../api/client";
import { TrackTable, type Track } from "../components/TrackTable";

export function TrackPage() {
  const [rows, setRows] = useState<Track[]>([]);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);

  const refresh = () =>
    apiGet<Track[]>("/api/track").then(setRows).catch(() => {});
  useEffect(() => { refresh(); }, []);

  const add = async () => {
    setLoading(true);
    try {
      const res = await apiPost<{ added: Track[] }>("/api/track", { text });
      message.success(`新增 ${res.added.length} 只`);
      setText("");
      await refresh();
    } catch {
      message.error("添加失败");
    } finally {
      setLoading(false);
    }
  };

  const remove = async (code: string, on: string) => {
    await apiDelete(`/api/track/${code}/${on}`).catch(() => {});
    await refresh();
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card title="添加跟踪(粘贴同花顺自选文本)">
        <Input.TextArea rows={6} value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="粘贴同花顺自选列表文本,自动识别 6 位代码" />
        <Button type="primary" loading={loading} onClick={add}
          style={{ marginTop: 12 }}>添加跟踪</Button>
      </Card>
      <Card title="我的跟踪(T+1/3/5/10 + 至今/最大涨幅/最大回撤)">
        <TrackTable rows={rows} onRemove={remove} />
      </Card>
    </Space>
  );
}
