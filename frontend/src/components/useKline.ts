import { useEffect, useState } from "react";
import { apiGet } from "../api/client";
import { type Bar } from "./KLineChart";

// 周期选项:默认日线(走历史行情库),其余为分钟线。
export const FREQ_OPTIONS = [
  { label: "日", value: "day" },
  { label: "1分", value: "1min" },
  { label: "5分", value: "5min" },
  { label: "15分", value: "15min" },
  { label: "30分", value: "30min" },
  { label: "60分", value: "60min" },
];
// 每个周期取多长的历史窗口(天)。
export const DAYS: Record<string, number> = {
  day: 400, "1min": 3, "5min": 12, "15min": 30, "30min": 60, "60min": 160,
};

export type KlineResp = {
  code: string; name: string; freq: string;
  bars: Bar[]; last_time: string | null;
};

// 拉 /api/kline + 盘中 ~60s 轮询。active=false 时不拉(浮窗关闭态)。
export function useKline(code: string, freq: string, active = true) {
  const [bars, setBars] = useState<Bar[]>([]);
  const [name, setName] = useState<string>("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!active || !code) return;
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const r = await apiGet<KlineResp>(
          `/api/kline/${code}?freq=${freq}&days=${DAYS[freq] ?? 5}`);
        if (!cancelled) { setBars(r.bars); setName(r.name); }
      } catch {
        /* 网络错误:保留上次数据 */
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, [code, freq, active]);

  return { bars, name, loading };
}
