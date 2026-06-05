import { useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { Segmented, Button, Space, Typography } from "antd";
import { KLineChart } from "../components/KLineChart";
import { FREQ_OPTIONS, useKline } from "../components/useKline";

// 独立全屏看图页 /chart/:code —— 图表占满屏,缩放/拖动更顺滑(不受 Modal 手势拦截)。
export function ChartPage() {
  const { code = "" } = useParams();
  const [sp] = useSearchParams();
  const nav = useNavigate();
  const [freq, setFreq] = useState("day");
  const { bars, name, loading } = useKline(code, freq);
  const title = name || sp.get("name") || code;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100vh - 140px)", minHeight: 420 }}>
      <Space wrap style={{ marginBottom: 12, justifyContent: "space-between", width: "100%" }}>
        <Space>
          <Button onClick={() => nav(-1)}>← 返回</Button>
          <Typography.Title level={4} style={{ margin: 0, whiteSpace: "nowrap" }}>
            {title} <Typography.Text type="secondary">{code}</Typography.Text>
          </Typography.Title>
        </Space>
        <Segmented options={FREQ_OPTIONS} value={freq} onChange={(v) => setFreq(v as string)} />
      </Space>
      {bars.length === 0 ? (
        <div style={{ flex: 1, display: "flex", alignItems: "center",
          justifyContent: "center", color: "#999" }}>
          {loading ? "加载中…" : "采集中,暂无数据"}
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0 }}>
          <KLineChart bars={bars} height="100%" />
        </div>
      )}
    </div>
  );
}
