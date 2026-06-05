"""单只决策 worker。用法:python scripts/run_one_decision.py --code 600519.SH --job 3"""
import sys, argparse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import DecisionJob
from app.data.quote_store import QuoteStore
from app.data.prices import latest_close
from app.data.fundamentals import build_fundamentals
from app.screener.earnings import TushareEarningsSource
from app.research.store import ResearchStore
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner
from app.trading.broker import PaperBroker


def run_one(session, job_id, code, graph, store, research, earnings=None):
    job = session.get(DecisionJob, job_id)
    job.status = "RUNNING"; session.commit()
    try:
        as_of = store.trading_dates(date.today(), 1)[0]
        bars = store.get_bars(code, date(as_of.year - 1, as_of.month, as_of.day), as_of)
        closes = [b.close for b in bars][-20:]
        rnote = research.latest(code)
        r = ({"sentiment": rnote.sentiment, "rating_consensus": rnote.rating_consensus,
              "summary": rnote.summary} if rnote else None)
        fundamentals = build_fundamentals(session, code, as_of, earnings=earnings)
        brief = build_brief(code, closes, {}, fundamentals, None, research=r)
        runner = DecisionRunner(session, graph, broker=PaperBroker(session),
                                account_id=1, price_of=lambda c: latest_close(store, c, as_of))
        out = runner.run(as_of, [brief])
        job.decision_id = out[0].id; job.status = "DONE"
    except Exception as e:  # noqa: BLE001
        job.status = "FAILED"; job.error = str(e)[:500]
    session.commit()


def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--job", type=int, required=True)
    a = ap.parse_args()
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    try:
        import tushare as ts
        earnings = TushareEarningsSource(ts.pro_api(s.tushare_token))
    except Exception:
        earnings = None  # 取不到增速也不挡决策
    run_one(session, a.job, a.code, DecisionGraph(_llm(s), rounds=s.debate_rounds),
            QuoteStore(session), ResearchStore(session), earnings=earnings)
    print(f"JOB_DONE job={a.job}", flush=True)


if __name__ == "__main__":
    main()
