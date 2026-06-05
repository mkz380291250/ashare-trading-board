import { type UTCTimestamp } from "lightweight-charts";
import { type Bar } from "./KLineChart";

export type Pt = { time: UTCTimestamp; value: number };

// 把「字面北京时间」转成 UTC 秒,让坐标轴直接显示原始 HH:MM(与浏览器时区无关)。
export function toSec(t: string): UTCTimestamp {
  const m = t.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (!m) return Math.floor(new Date(t).getTime() / 1000) as UTCTimestamp;
  return Math.floor(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) / 1000) as UTCTimestamp;
}

// 简单移动平均(收盘价),前 n-1 根不出点。
export function ma(bars: Bar[], n: number): Pt[] {
  const out: Pt[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].c;
    if (i >= n) sum -= bars[i - n].c;
    if (i >= n - 1) out.push({ time: toSec(bars[i].t), value: +(sum / n).toFixed(3) });
  }
  return out;
}

// EMA(指数移动平均),首值取序列第一个值。
function ema(vals: number[], n: number): number[] {
  const k = 2 / (n + 1);
  const out: number[] = [];
  let prev = vals[0] ?? 0;
  for (let i = 0; i < vals.length; i++) {
    prev = i === 0 ? vals[0] : vals[i] * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

export type Macd = { dif: Pt[]; dea: Pt[]; hist: { time: UTCTimestamp; value: number; up: boolean }[] };

// MACD(12,26,9):DIF=EMA12-EMA26,DEA=EMA9(DIF),柱=(DIF-DEA)*2。
export function macd(bars: Bar[]): Macd {
  const close = bars.map((b) => b.c);
  const e12 = ema(close, 12);
  const e26 = ema(close, 26);
  const dif = e12.map((v, i) => v - e26[i]);
  const dea = ema(dif, 9);
  const out: Macd = { dif: [], dea: [], hist: [] };
  for (let i = 0; i < bars.length; i++) {
    const t = toSec(bars[i].t);
    const h = (dif[i] - dea[i]) * 2;
    out.dif.push({ time: t, value: +dif[i].toFixed(4) });
    out.dea.push({ time: t, value: +dea[i].toFixed(4) });
    out.hist.push({ time: t, value: +h.toFixed(4), up: h >= 0 });
  }
  return out;
}

export type Kdj = { k: Pt[]; d: Pt[]; j: Pt[] };

// KDJ(9,3,3):RSV 用 9 日高低,K/D 平滑系数 1/3,J=3K-2D。
export function kdj(bars: Bar[], n = 9): Kdj {
  const out: Kdj = { k: [], d: [], j: [] };
  let kPrev = 50;
  let dPrev = 50;
  for (let i = 0; i < bars.length; i++) {
    const lo = i < n - 1 ? bars.slice(0, i + 1) : bars.slice(i - n + 1, i + 1);
    let ll = Infinity;
    let hh = -Infinity;
    for (const b of lo) { ll = Math.min(ll, b.l); hh = Math.max(hh, b.h); }
    const rsv = hh === ll ? 50 : ((bars[i].c - ll) / (hh - ll)) * 100;
    const kv = (2 / 3) * kPrev + (1 / 3) * rsv;
    const dv = (2 / 3) * dPrev + (1 / 3) * kv;
    const jv = 3 * kv - 2 * dv;
    kPrev = kv; dPrev = dv;
    const t = toSec(bars[i].t);
    out.k.push({ time: t, value: +kv.toFixed(3) });
    out.d.push({ time: t, value: +dv.toFixed(3) });
    out.j.push({ time: t, value: +jv.toFixed(3) });
  }
  return out;
}
