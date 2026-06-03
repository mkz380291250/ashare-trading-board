"""Resolve theme -> concept index -> member stocks, respecting tushare's
ths_member 1-call/minute limit. Caches result to a JSON file for reuse by the
screener / backtest. Run detached (it is slow on purpose)."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.data.rate_limiter import RateLimiter

# theme label -> keywords matched against concept index names
THEME_KEYWORDS = {
    "英伟达链": ["英伟达", "CPO", "光模块"],
    "半导体": ["半导体"],
    "芯片": ["芯片", "国产芯片", "存储芯片"],
    "算力": ["算力", "数据中心"],
    "电力": ["电力", "电网"],
}
CONCEPTS_PER_THEME = 2          # cap to bound runtime (each ths_member = 1/min)
OUT = "/tmp/theme_members.json"


def main():
    import tushare as ts
    pro = ts.pro_api(get_settings().tushare_token)
    idx_limiter = RateLimiter(max_calls=1, period_s=2.0)      # ths_index is lenient
    mem_limiter = RateLimiter(max_calls=1, period_s=61.0)     # ths_member: 1/min

    idx_limiter.acquire()
    idx = pro.ths_index()
    concepts = idx[idx["type"] == "N"].copy()
    concepts["count"] = concepts["count"].fillna(0)

    result = {}
    for theme, kws in THEME_KEYWORDS.items():
        matched = concepts[concepts["name"].str.contains("|".join(kws), na=False)]
        matched = matched.sort_values("count", ascending=False).head(CONCEPTS_PER_THEME)
        codes = set()
        for _, row in matched.iterrows():
            ic, nm = row["ts_code"], row["name"]
            mem_limiter.acquire()
            try:
                mem = pro.ths_member(ts_code=ic)
                got = [str(x) for x in mem["con_code"].tolist()]
                codes.update(got)
                print(f"{theme} <- {nm} ({ic}): {len(got)} members", flush=True)
            except Exception as e:
                print(f"{theme} <- {nm} ({ic}): FAILED {e!r}", flush=True)
        result[theme] = sorted(codes)
        print(f"== {theme}: {len(codes)} total stocks ==", flush=True)

    Path(OUT).write_text(json.dumps(result, ensure_ascii=False))
    print(f"WROTE {OUT} themes={list(result.keys())} "
          f"sizes={ {k: len(v) for k, v in result.items()} }", flush=True)
    print("MEMBERS_DONE", flush=True)


if __name__ == "__main__":
    main()
