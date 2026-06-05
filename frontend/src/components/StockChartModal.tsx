import { useEffect, useState } from "react";
import { Modal, Segmented } from "antd";
import { apiGet } from "../api/client";
import { KLineChart, type Bar } from "./KLineChart";

const FREQS = ["1min", "5min", "15min", "30min", "60min"];
// 每个周期取多长的历史窗口(天)。周期越大看得越远(库里约存 320 根/周期)。
const DAYS: Record<string, number> = {
  "1min": 3, "5min": 12, "15min": 30, "30min": 60, "60min": 160,
};

type KlineResp = {
  code: string; name: string; freq: string;
  bars: Bar[]; last_time: string | null;
};

// 弹出抽屉/模态:周期切换 + 拉 /api/kline 喂 KLineChart + 盘中 ~60s 轮询。
// 端点只读库,响应快;库里没数据则显示「采集中」。
export function StockChartModal({ code, name, open, onClose }: {
  code: string; name?: string; open: boolean; onClose: () => void;
}) {
  const [freq, setFreq] = useState("1min");
  const [bars, setBars] = useState<Bar[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !code) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const r = await apiGet<KlineResp>(
          `/api/kline/${code}?freq=${freq}&days=${DAYS[freq] ?? 5}`);
        if (!cancelled) setBars(r.bars);
      } catch {
        /* 网络错误:保留上次数据 */
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const id = setInterval(load, 60000); // 盘中准实时
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [open, code, freq]);

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={880}
      destroyOnHidden
      title={name ? `${name}(${code})` : code}
    >
      <Segmented
        options={FREQS}
        value={freq}
        onChange={(v) => setFreq(v as string)}
        style={{ marginBottom: 12 }}
      />
      {bars.length === 0 ? (
        <div style={{
          height: 420, display: "flex", alignItems: "center",
          justifyContent: "center", color: "#999",
        }}>
          {loading ? "加载中…" : "采集中,暂无分钟数据"}
        </div>
      ) : (
        <KLineChart bars={bars} />
      )}
    </Modal>
  );
}
