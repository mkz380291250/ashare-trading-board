import { useState } from "react";
import { Modal, Segmented, Button } from "antd";
import { useNavigate } from "react-router-dom";
import { KLineChart } from "./KLineChart";
import { FREQ_OPTIONS, useKline } from "./useKline";

// 浮窗:快速瞄一眼。周期切换 + /api/kline + 盘中 ~60s 轮询(useKline)。
// 「全屏」按钮跳到独立大页面 /chart/:code,缩放/拖动更顺滑。
export function StockChartModal({ code, name, open, onClose }: {
  code: string; name?: string; open: boolean; onClose: () => void;
}) {
  const [freq, setFreq] = useState("day");
  const { bars, loading } = useKline(code, freq, open);
  const nav = useNavigate();

  const openFull = () => {
    onClose();
    nav(`/chart/${code}${name ? `?name=${encodeURIComponent(name)}` : ""}`);
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={880}
      destroyOnHidden
      title={name ? `${name}(${code})` : code}
    >
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 12 }}>
        <Segmented options={FREQ_OPTIONS} value={freq}
                   onChange={(v) => setFreq(v as string)} />
        <Button size="small" onClick={openFull}>全屏 ⛶</Button>
      </div>
      {bars.length === 0 ? (
        <div style={{
          height: 420, display: "flex", alignItems: "center",
          justifyContent: "center", color: "#999",
        }}>
          {loading ? "加载中…" : "采集中,暂无数据"}
        </div>
      ) : (
        <KLineChart bars={bars} />
      )}
    </Modal>
  );
}
