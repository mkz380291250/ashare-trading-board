"""Backtest the 大阳线 signal on the fixed theme universe.

Signal: a daily gain > 9.5% (大阳线) on any trading day in the window
[t-13, t-10] (10 to 13 trading days before the latest bar in the DB).
For each hit, measure forward T+3 / T+5 / T+10 returns FROM the signal day.
Then split out 业绩好 stocks (净利 YoY >= 20% AND 营收 YoY > 0).

All prices are dividend/split-adjusted (close * adj_factor) so the signal and
the forward returns are not distorted by ex-rights days. Bars come from the
local historical DB; only the (few dozen) signal hits hit tushare for earnings.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select

from app.config import get_settings
from app.data.quote_store import QuoteStore
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.screener.earnings import TushareEarningsSource, passes_earnings

GAIN = 9.5          # 大阳线 threshold (%)
BACK = 10           # signal window ends 10 trading days ago ...
WIN = 4             # ... and spans 4 days back to t-13


def adj_close(b):
    return b.close * b.adj_factor


def trading_calendar(store) -> list:
    # ORM returns date objects (raw SQL would yield strings -> type mismatch)
    return sorted(store.s.scalars(select(distinct(DailyQuote.trade_date))).all())


def main():
    s = get_settings()
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)

    cache = json.loads(Path("/tmp/theme_members.json").read_text())
    theme_of = {}
    for theme, codes in cache.items():
        for c in codes:
            theme_of.setdefault(c, theme)
    universe = list(theme_of)

    cal = trading_calendar(store)
    last = cal[-1]
    # window [t-13, t-10] inclusive: indices -(BACK+WIN) .. -(BACK+1)
    window = set(cal[-(BACK + WIN):-BACK])
    fetch_start = cal[-(BACK + WIN + 5)]  # margin for the prior-close of t-13
    print(f"latest bar {last} | 大阳线 window {min(window)} .. {max(window)} "
          f"(>{GAIN}%) | universe {len(universe)} stocks", flush=True)

    hits = []
    for code in universe:
        bars = store.get_bars(code, fetch_start, last)
        if len(bars) < 2:
            continue
        # earliest day in window whose adjusted gain > GAIN
        si = None
        for i in range(1, len(bars)):
            if bars[i].trade_date in window:
                pct = (adj_close(bars[i]) / adj_close(bars[i - 1]) - 1) * 100
                if pct > GAIN:
                    si = i
                    sig_pct = pct
                    break
        if si is None:
            continue
        entry = adj_close(bars[si])

        def ret(n):
            j = si + n
            if j >= len(bars):
                return None
            return round((adj_close(bars[j]) / entry - 1) * 100, 1)

        hits.append({
            "code": code, "theme": theme_of[code],
            "sig_date": bars[si].trade_date, "sig_pct": round(sig_pct, 1),
            "entry": round(bars[si].close, 2),  # actual close (returns use adjusted)
            "t3": ret(3), "t5": ret(5), "t10": ret(10),
            "np_yoy": None, "rev_yoy": None,
        })

    # earnings only for the hits
    try:
        import tushare as ts
        esrc = TushareEarningsSource(ts.pro_api(s.tushare_token))
    except Exception:
        esrc = None
    if esrc is not None:
        for h in hits:
            try:
                e = esrc.latest(h["code"])
            except Exception:
                e = None
            if e is not None:
                h["np_yoy"], h["rev_yoy"] = round(e.np_yoy, 1), round(e.rev_yoy, 1)
                h["_e"] = e

    def good(h):
        return passes_earnings(h.get("_e"))

    # detailed CSV (utf-8-sig so Excel renders Chinese); 业绩好 first, then theme
    import csv
    csv_path = "/tmp/dayang_backtest.csv"
    cols = [("theme", "题材"), ("code", "代码"), ("sig_date", "大阳线日期"),
            ("sig_pct", "大阳线涨幅%"), ("entry", "入选价(收盘)"),
            ("t3", "T+3%"), ("t5", "T+5%"), ("t10", "T+10%"),
            ("np_yoy", "净利YoY%"), ("rev_yoy", "营收YoY%")]
    ordered = sorted(hits, key=lambda x: (not good(x), x["theme"], x["code"]))
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([h for _, h in cols] + ["业绩好"])
        for h in ordered:
            w.writerow([h[k] for k, _ in cols] + ["是" if good(h) else ""])
    print(f"CSV -> {csv_path} ({len(ordered)} 行)", flush=True)

    print(f"\n=== 大阳线(>{GAIN}%)命中 {len(hits)} 只 ===", flush=True)
    for h in sorted(hits, key=lambda x: (x["theme"], x["code"])):
        ep = "" if h["np_yoy"] is None else f" | 净利{h['np_yoy']}% 营收{h['rev_yoy']}%"
        star = " ★业绩好" if good(h) else ""
        print(f"  [{h['theme']}] {h['code']} {h['sig_date']} 大阳{h['sig_pct']}% "
              f"-> T+3 {h['t3']}% T+5 {h['t5']}% T+10 {h['t10']}%{ep}{star}", flush=True)

    def agg(rows, label):
        print(f"--- {label} (n={len(rows)}) ---", flush=True)
        for k in ("t3", "t5", "t10"):
            v = [r[k] for r in rows if r[k] is not None]
            if not v:
                print(f"  {k}: n/a", flush=True)
                continue
            avg = round(sum(v) / len(v), 2)
            win = round(100 * sum(x > 0 for x in v) / len(v), 0)
            print(f"  {k}: avg {avg}%  win% {win}  n={len(v)}", flush=True)

    print(flush=True)
    agg(hits, "全部命中")
    agg([h for h in hits if good(h)], "业绩好(净利≥20% & 营收>0)")
    print("BACKTEST_DONE", flush=True)


if __name__ == "__main__":
    main()
