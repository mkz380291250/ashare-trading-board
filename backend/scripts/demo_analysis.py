"""End-to-end demo: for a few codes, fetch research (tushare+EastMoney) -> claude
summary -> build brief -> run the claude multi-agent DecisionGraph -> print verdict.
Usage: .venv/bin/python scripts/demo_analysis.py 600519.SH 603011.SH 300197.SZ
"""
import sys
import time
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.decision.llm import LocalClaudeClient
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.research.sources import TushareResearchSource, EastMoneyNewsSource, CompositeSource
from app.research.analyzer import ResearchAnalyzer
from app.data.rate_limiter import RateLimiter

CODES = sys.argv[1:] or ["600519.SH", "603011.SH", "300197.SZ"]
ROUNDS = 1  # keep the multi-agent debate to 1 round for a faster demo


def factors_and_fundamentals(bars):
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    last = closes[-1]
    mom_5d = last / closes[-6] - 1 if len(closes) > 6 else 0.0
    breakout = last / max(highs[-20:]) if highs else 1.0
    vols = [b.volume for b in bars]
    vol_ratio = (vols[-1] / (sum(vols[-6:-1]) / 5)) if len(vols) > 6 and sum(vols[-6:-1]) else 1.0
    return {"mom_5d": round(mom_5d, 4), "breakout": round(breakout, 4),
            "vol_ratio": round(vol_ratio, 2)}


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    llm = LocalClaudeClient(bin_path=s.claude_bin)

    as_of = store.trading_dates(date.today(), 1)[0]
    start = date(as_of.year - 1, as_of.month, as_of.day)

    # research source (fault tolerant)
    research_src = None
    try:
        import tushare as ts
        pro = ts.pro_api(s.tushare_token)
        research_src = CompositeSource([
            TushareResearchSource(pro, limiter=RateLimiter(max_calls=1, period_s=60.0)),
            EastMoneyNewsSource(),
        ])
    except Exception as e:
        print(f"[research source init failed: {e!r}]", flush=True)
    analyzer = ResearchAnalyzer(llm)

    graph = DecisionGraph(llm, rounds=ROUNDS)

    for code in CODES:
        t0 = time.time()
        print(f"\n{'='*60}\n>>> {code}  (as_of={as_of})", flush=True)
        bars = store.get_bars(code, start, as_of)
        if len(bars) < 10:
            print(f"  skip: only {len(bars)} bars", flush=True)
            continue
        # qfq closes
        fl = bars[-1].adj_factor or 1.0
        closes = [round(b.close * (b.adj_factor or 1.0) / fl, 2) for b in bars][-20:]
        fac = factors_and_fundamentals(bars)

        # research
        research = None
        items = []
        if research_src is not None:
            try:
                items = research_src.fetch(code, as_of)
            except Exception as e:
                print(f"  [research fetch error: {e!r}]", flush=True)
        if items:
            note = analyzer.analyze(code, items)
            research = {"sentiment": note.sentiment,
                        "rating_consensus": note.rating_consensus,
                        "summary": note.summary}
            print(f"  研报: {len(items)} 条 -> 情绪={note.sentiment} "
                  f"评级={note.rating_consensus} | {note.summary[:60]}", flush=True)
        else:
            print("  研报: 无数据(源不可达或无近期研报),分析师按中性处理", flush=True)

        brief = build_brief(code, closes, fac, {}, holding=None, research=research)
        dec = graph.run(brief)
        print(f"  >>> 结论: {dec.action}  信心={dec.confidence}  建议股数={dec.shares}  "
              f"(用时 {time.time()-t0:.0f}s)", flush=True)
        # print the trader + risk-manager sections (last two meaningful voices)
        for seg in dec.reasoning.split("### "):
            if seg.startswith("交易员") or seg.startswith("风控经理"):
                print("  --- " + seg.strip()[:400], flush=True)

    print("\nDEMO_DONE", flush=True)


if __name__ == "__main__":
    main()
