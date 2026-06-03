import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func
from app.config import get_settings
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import Position, DiscoveryPick
from app.data.quote_store import QuoteStore
from app.research.store import ResearchStore
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.decision.brief import build_brief
from app.decision.graph import DecisionGraph
from app.decision.runner import DecisionRunner


def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def main():
    s = get_settings()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    research = ResearchStore(session)

    as_of = store.trading_dates(date.today(), 1)[0]
    holds = {p.code: p for p in session.scalars(select(Position)).all()}
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    top = [r.code for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)).all()] if top_date else []
    codes = sorted(set(holds) | set(top))

    briefs = []
    start = date(as_of.year - 1, as_of.month, as_of.day)
    for code in codes:
        bars = store.get_bars(code, start, as_of)
        closes = [b.close for b in bars][-20:]
        h = holds.get(code)
        holding = {"shares": h.shares, "cost": h.cost} if h else None
        rnote = research.latest(code)
        r = ({"sentiment": rnote.sentiment,
              "rating_consensus": rnote.rating_consensus,
              "summary": rnote.summary} if rnote else None)
        briefs.append(build_brief(code, closes, {}, {}, holding, research=r))

    runner = DecisionRunner(session, DecisionGraph(_llm(s), rounds=s.debate_rounds))
    out = runner.run(as_of, briefs)
    for d in out:
        print(f"{d.code}  {d.action}  conf={d.confidence}  shares={d.shares}", flush=True)
    print(f"DECISIONS_DONE as_of={as_of} n={len(out)}", flush=True)


if __name__ == "__main__":
    main()
