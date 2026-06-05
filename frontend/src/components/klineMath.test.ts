import { describe, it, expect } from "vitest";
import { ma, macd, kdj, toSec, type Pt } from "./klineMath";
import { type Bar } from "./KLineChart";

// 生成一段递增的假 K 线,够长以覆盖 MACD/KDJ 的窗口。
const bars: Bar[] = Array.from({ length: 40 }, (_, i) => ({
  t: `2026-06-04T09:${String(31 + (i % 29)).padStart(2, "0")}:00`,
  o: 10 + i * 0.1, h: 10.5 + i * 0.1, l: 9.5 + i * 0.1, c: 10 + i * 0.1, v: 100 + i,
}));

const last = (a: Pt[]) => a[a.length - 1].value;

describe("klineMath", () => {
  it("toSec 解析字面北京时间为固定 UTC 秒(与时区无关)", () => {
    expect(toSec("2026-06-04T09:31:00")).toBe(Math.floor(Date.UTC(2026, 5, 4, 9, 31) / 1000));
  });

  it("ma 前 n-1 根不出点,值等于窗口均值", () => {
    const m5 = ma(bars, 5);
    expect(m5.length).toBe(bars.length - 4);
    // 末 5 根收盘的均值
    const tail = bars.slice(-5).reduce((s, b) => s + b.c, 0) / 5;
    expect(last(m5)).toBeCloseTo(tail, 3);
  });

  it("macd 长度对齐,单调上涨时 DIF>0 且柱为正", () => {
    const m = macd(bars);
    expect(m.dif.length).toBe(bars.length);
    expect(m.hist.length).toBe(bars.length);
    expect(last(m.dif)).toBeGreaterThan(0);
    expect(m.hist[m.hist.length - 1].up).toBe(true);
  });

  it("kdj 数值落在合理区间,单调上涨时 K 偏高", () => {
    const r = kdj(bars);
    expect(r.k.length).toBe(bars.length);
    expect(last(r.k)).toBeGreaterThan(50);
    expect(last(r.k)).toBeLessThanOrEqual(100);
    // J = 3K - 2D
    const i = bars.length - 1;
    expect(r.j[i].value).toBeCloseTo(3 * r.k[i].value - 2 * r.d[i].value, 2);
  });
});
