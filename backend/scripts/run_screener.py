import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.data.rate_limiter import RateLimiter
from app.screener.themes import StaticThemeSource
from app.screener.earnings import TushareEarningsSource
from app.screener.screener import Screener
from app.screener.pool import WatchPool

# theme label -> keywords matched against tushare concept index names (ths_index)
THEME_KEYWORDS = {
    "英伟达算力链": ["英伟达", "CPO", "算力"],
    "半导体芯片": ["半导体", "芯片"],
    "算力": ["算力", "数据中心"],
    "电力": ["电力"],
}


def resolve_themes(pro, limiter) -> dict[str, list[str]]:
    """For each theme, union the members of concept indices whose name matches
    any keyword. Returns {theme: [codes]}."""
    limiter.acquire()
    idx = pro.ths_index()
    concepts = idx[idx["type"] == "N"]  # N = concept
    out: dict[str, list[str]] = {}
    for theme, kws in THEME_KEYWORDS.items():
        codes: set[str] = set()
        matched = concepts[concepts["name"].str.contains("|".join(kws), na=False)]
        for ic in matched["ts_code"].tolist():
            limiter.acquire()
            try:
                mem = pro.ths_member(ts_code=ic)
                codes.update(str(x) for x in mem["con_code"].tolist())
            except Exception as e:
                print(f"  skip concept {ic}: {e!r}", flush=True)
        out[theme] = sorted(codes)
        print(f"theme {theme}: {len(matched)} concepts -> {len(codes)} stocks", flush=True)
    return out


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)

    import tushare as ts
    pro = ts.pro_api(s.tushare_token)
    limiter = RateLimiter(max_calls=100, period_s=60.0)

    themes = StaticThemeSource(resolve_themes(pro, limiter))

    class LimitedEarnings(TushareEarningsSource):
        def latest(self, code):
            limiter.acquire(); return super().latest(code)

    today = date.today()

    def bars_provider(code):
        return store.get_bars(code, date(today.year - 1, today.month, today.day), today)

    sc = Screener(themes=themes, earnings=LimitedEarnings(pro), bars_provider=bars_provider)
    picks = sc.run(as_of=today)
    pool = WatchPool(session)
    for p in picks:
        pool.add(p.code, p.theme, p.as_of, p.entry_close, p.trigger)
        print(f"PICK {p.code} {p.theme} @ {p.entry_close} {p.trigger}", flush=True)
    for entry in pool.list():
        bars = store.get_bars(entry.code, entry.first_selected_on, today)
        pool.update_forward_returns(entry.code, entry.first_selected_on, bars)
    print(f"SCREENER_DONE picks={len(picks)} pool={len(pool.list())}", flush=True)


if __name__ == "__main__":
    main()
