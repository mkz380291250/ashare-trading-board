"""Backtest: as of 10 trading days ago, which curated theme stocks showed the
screen signal (>7% bullish candle in the prior 3 days, not at top), and how did
they actually perform T+3 / T+5 / T+10. Earnings (np_yoy/rev_yoy) annotated where
the tushare endpoint allows. Bars come from the local historical DB (no network)."""
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.data.quote_store import QuoteStore
from app.screener.filters import has_big_yang, not_at_top, day_pct

AS_OF = date(2026, 5, 19)
WIN_START = date(2025, 5, 19)
FWD = [date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22), date(2026, 5, 25),
       date(2026, 5, 26), date(2026, 5, 27), date(2026, 5, 28), date(2026, 5, 29),
       date(2026, 6, 1), date(2026, 6, 2)]  # T+1 .. T+10

THEMES = {
    "英伟达链": ["300308.SZ", "300502.SZ", "300394.SZ", "002281.SZ", "300570.SZ",
              "603083.SH", "002463.SZ", "300476.SZ", "601138.SH", "000988.SZ", "300620.SZ",
              "002384.SZ", "002916.SZ", "002938.SZ", "600183.SH", "300548.SZ", "688498.SH",
              "301205.SZ", "002446.SZ", "300353.SZ", "688141.SH"],
    "半导体": ["688981.SH", "002371.SZ", "688012.SH", "603986.SH", "603501.SH", "600584.SH",
             "688396.SH", "688072.SH", "688082.SH", "688126.SH", "688516.SH", "688037.SH",
             "688200.SH", "688120.SH", "688728.SH", "603893.SH", "688107.SH", "688362.SH",
             "002185.SZ", "688234.SH", "002129.SZ", "688362.SH"],
    "芯片": ["688256.SH", "688041.SH", "688047.SH", "002049.SZ", "688385.SH", "688008.SH",
            "300782.SZ", "600460.SH", "002156.SZ", "300223.SZ", "688521.SH", "603160.SH",
            "688595.SH", "605111.SH", "688368.SH", "002180.SZ", "300661.SZ", "688141.SH"],
    "算力": ["603019.SH", "000977.SZ", "000034.SZ", "300442.SZ", "301236.SZ", "000938.SZ",
            "002230.SZ", "300383.SZ", "601138.SH", "300738.SZ", "300846.SZ", "603881.SH",
            "002439.SZ", "688561.SH", "300468.SZ"],
    "电力": ["600900.SH", "600406.SH", "600011.SH", "600886.SH", "600674.SH", "600905.SH",
            "601985.SH", "600795.SH", "003816.SZ", "600025.SH", "600021.SH", "001289.SH",
            "000591.SZ", "003035.SZ", "600578.SH", "000539.SZ", "002028.SZ", "600312.SH",
            "601126.SH", "600886.SH"],
}


def main():
    s = get_settings()
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)

    # earnings is optional (tushare may rate-limit); annotate best-effort
    try:
        import tushare as ts
        pro = ts.pro_api(s.tushare_token)
    except Exception:
        pro = None

    def earnings(code):
        if pro is None:
            return None
        try:
            df = pro.fina_indicator(ts_code=code)
            if df is None or df.empty:
                return None
            r = df.sort_values("end_date").iloc[-1]
            return (float(r.get("netprofit_yoy") or 0), float(r.get("or_yoy") or 0))
        except Exception:
            return None

    all_rows = []
    for theme, codes in THEMES.items():
        for code in dict.fromkeys(codes):
            hist = store.get_bars(code, WIN_START, AS_OF)
            if len(hist) < 2 or hist[-1].trade_date != AS_OF:
                continue  # not in DB / suspended on as_of
            if not has_big_yang(hist, window=3, threshold=7.0):
                continue
            if not not_at_top(hist):
                continue
            entry = hist[-1].close
            big_pct = max(day_pct(hist[i - 1].close, hist[i].close)
                          for i in range(len(hist) - 3, len(hist)))
            fwd = {b.trade_date: b.close for b in store.get_bars(code, AS_OF, FWD[-1])}

            def ret(n):
                c = fwd.get(FWD[n - 1])
                return None if c is None else round((c / entry - 1) * 100, 1)
            e = earnings(code)
            all_rows.append({"theme": theme, "code": code, "entry": entry,
                             "big_pct": round(big_pct, 1),
                             "t3": ret(3), "t5": ret(5), "t10": ret(10),
                             "np_yoy": None if not e else round(e[0], 1),
                             "rev_yoy": None if not e else round(e[1], 1)})

    print(f"=== Backtest as_of {AS_OF} (signal: >7% candle in prior 3d + not-at-top) ===", flush=True)
    print(f"universe (curated) -> {sum(len(set(v)) for v in THEMES.values())} stocks; "
          f"signal hits: {len(all_rows)}", flush=True)
    for r in all_rows:
        ep = "" if r["np_yoy"] is None else f" | 净利{r['np_yoy']}% 营收{r['rev_yoy']}%"
        print(f"  [{r['theme']}] {r['code']} 入选价{r['entry']} 大阳{r['big_pct']}% "
              f"-> T+3 {r['t3']}% T+5 {r['t5']}% T+10 {r['t10']}%{ep}", flush=True)

    def avg(key, rows):
        vals = [x[key] for x in rows if x[key] is not None]
        return None if not vals else round(sum(vals) / len(vals), 2)

    def winrate(key, rows):
        vals = [x[key] for x in rows if x[key] is not None]
        return None if not vals else round(100 * sum(v > 0 for v in vals) / len(vals), 0)

    print("--- aggregate (all signal hits) ---", flush=True)
    for k in ("t3", "t5", "t10"):
        print(f"  {k}: avg {avg(k, all_rows)}%  win% {winrate(k, all_rows)}  n={len([x for x in all_rows if x[k] is not None])}", flush=True)
    strong = [x for x in all_rows if x["np_yoy"] is not None and x["np_yoy"] >= 20 and x["rev_yoy"] > 0]
    if strong:
        print(f"--- aggregate (signal + 净利≥20% & 营收>0, n={len(strong)}) ---", flush=True)
        for k in ("t3", "t5", "t10"):
            print(f"  {k}: avg {avg(k, strong)}%  win% {winrate(k, strong)}", flush=True)
    print("BACKTEST_DONE", flush=True)


if __name__ == "__main__":
    main()
