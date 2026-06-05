"""Run the multi-agent debate over a watchlist and PERSIST each decision to the
decisions table IMMEDIATELY (commit per stock), so a kill mid-run never loses
completed work. Frontend /decisions then shows them (PENDING) with role debate.
Usage: .venv/bin/python scripts/decide_watchlist.py 688126.SH 688146.SH ...
"""
import sys
import time
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import Decision
from app.data.quote_store import QuoteStore
from app.decision.llm import LocalClaudeClient
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.research.sources import TushareResearchSource, EastMoneyNewsSource, CompositeSource
from app.research.analyzer import ResearchAnalyzer
from app.data.rate_limiter import RateLimiter

CODES = sys.argv[1:]
ROUNDS = 1


def factors_of(bars):
    closes = [b.close for b in bars]; highs = [b.high for b in bars]
    last = closes[-1]
    mom_5d = last / closes[-6] - 1 if len(closes) > 6 else 0.0
    breakout = last / max(highs[-20:]) if highs else 1.0
    vols = [b.volume for b in bars]
    vr = (vols[-1] / (sum(vols[-6:-1]) / 5)) if len(vols) > 6 and sum(vols[-6:-1]) else 1.0
    return {"mom_5d": round(mom_5d, 4), "breakout": round(breakout, 4), "vol_ratio": round(vr, 2)}


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    llm = LocalClaudeClient(bin_path=s.claude_bin)
    as_of = store.trading_dates(date.today(), 1)[0]
    start = date(as_of.year - 1, as_of.month, as_of.day)

    src = None
    try:
        import tushare as ts
        pro = ts.pro_api(s.tushare_token)
        src = CompositeSource([
            TushareResearchSource(pro, limiter=RateLimiter(max_calls=1, period_s=60.0)),
            EastMoneyNewsSource()])
    except Exception as e:
        print(f"[research init failed {e!r}]", flush=True)
    analyzer = ResearchAnalyzer(llm)
    graph = DecisionGraph(llm, rounds=ROUNDS)

    for i, code in enumerate(CODES, 1):
        t0 = time.time()
        print(f"\n[{i}/{len(CODES)}] >>> {code}", flush=True)
        bars = store.get_bars(code, start, as_of)
        if len(bars) < 10:
            print(f"  skip ({len(bars)} bars)", flush=True); continue
        fl = bars[-1].adj_factor or 1.0
        closes = [round(b.close * (b.adj_factor or 1.0) / fl, 2) for b in bars][-20:]
        research = None
        try:
            items = src.fetch(code, as_of) if src else []
            if items:
                note = analyzer.analyze(code, items)
                research = {"sentiment": note.sentiment,
                            "rating_consensus": note.rating_consensus, "summary": note.summary}
        except Exception as e:
            print(f"  [research err {e!r}]", flush=True)
        brief = build_brief(code, closes, factors_of(bars), {}, holding=None, research=research)
        dec = graph.run(brief)
        # delete-then-insert + COMMIT NOW (idempotent, crash-safe)
        session.execute(delete(Decision).where(Decision.as_of == as_of, Decision.code == code))
        session.add(Decision(as_of=as_of, code=code, action=dec.action,
                             confidence=dec.confidence, shares=dec.shares,
                             reasoning=dec.reasoning, status="PENDING", created_at=as_of))
        session.commit()
        print(f"  SAVED {dec.action} conf={dec.confidence} shares={dec.shares} "
              f"({time.time()-t0:.0f}s)", flush=True)

    print("WATCHLIST_DONE", flush=True)


if __name__ == "__main__":
    main()
