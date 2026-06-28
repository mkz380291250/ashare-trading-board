"""每日编排:全市场行情 -> qlib 重建 -> 跟踪表指标刷新。
可命令行运行(python scripts/daily_full.py),也被 APScheduler 调用 run_all()。"""
import subprocess
import sys
import traceback
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, func
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
import app.db.models  # noqa: F401
from app.data.quote_store import QuoteStore
from app.screener.tracklist import Tracker
from app.db.models import Position, DiscoveryPick
from app.data.prices import DictPriceProvider, latest_close
from app.trading.broker import PaperBroker
from app.decision.graph import DecisionGraph
from app.decision.brief import build_brief
from app.decision.llm import LocalClaudeClient, DeepSeekClient
from app.decision.daily_pipeline import run_daily_decisions
from app.reporting.daily_summary import build_daily_summary

PY = sys.executable


def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin)


def _session():
    return make_session_factory(make_engine())()


def step_quotes() -> None:
    subprocess.run([PY, str(ROOT / "scripts" / "daily_update_quotes.py")],
                   cwd=ROOT, check=True)


def step_qlib() -> None:
    s = get_settings()
    subprocess.run([PY, str(ROOT / "scripts" / "build_qlib_data.py"),
                    "--qlib-dir", s.qlib_data_dir], cwd=ROOT, check=True)


def step_tracklist() -> None:
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    tr = Tracker(session)
    for e in tr.list():
        bars = store.get_bars(e.code, e.added_on, date.today())
        if bars:
            tr.update_metrics(e.code, e.added_on, bars)


def step_select() -> None:
    from app.backtest.qlib_data import init_qlib
    from app.factors.frozen import load_frozen
    from app.discovery.qlib_provider import run_qlib_discovery
    from scripts.freeze_factors import frozen_path
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    init_qlib(s.qlib_data_dir)
    from qlib.data import D
    frozen = load_frozen(frozen_path(s))
    insts = D.list_instruments(D.instruments(frozen.universe), as_list=True)
    run_qlib_discovery(session, as_of, frozen, insts)


def step_debate() -> None:
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    if top_date != as_of:
        raise RuntimeError(
            f"step_debate: 无当日选股产物(最新={top_date}, 期望={as_of}),跳过")
    ranking = [(r.code, r.score) for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)
        .order_by(DiscoveryPick.rank)).all()] if top_date else []
    if not ranking:
        raise RuntimeError("step_debate: 无 DiscoveryPick 产物,跳过(先跑 step_select)")
    holds = {p.code: p for p in session.scalars(
        select(Position).where(Position.account_id == 1)).all()}
    held = set(holds)

    def brief_builder(codes):
        start = date(as_of.year - 1, as_of.month, as_of.day)
        out = []
        for code in codes:
            bars = store.get_bars(code, start, as_of)
            closes = [b.close for b in bars][-20:]
            h = holds.get(code)
            holding = {"shares": h.shares, "cost": h.cost} if h else None
            out.append(build_brief(code, closes, {}, {}, holding))
        return out

    summary = run_daily_decisions(
        session, as_of, ranking, held, graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
        brief_builder=brief_builder, broker=PaperBroker(session),
        price_of=lambda c: latest_close(store, c, as_of),
        target=s.target_positions, quality_pctl=s.quality_pctl,
        min_confidence=s.min_confidence, max_debate=s.max_debate, account_id=1)
    print(build_daily_summary(session, as_of, account_id=1), flush=True)
    print(f"DEBATE_DONE {summary}", flush=True)


def step_mark() -> None:
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    held = session.scalars(select(Position).where(Position.account_id == 1)).all()
    prices = DictPriceProvider({p.code: (latest_close(store, p.code, as_of) or 0.0)
                               for p in held})
    PaperBroker(session).mark_to_market(1, prices, as_of)


def step_attribution() -> None:
    from app.attribution.outcomes import backfill_outcomes
    from app.attribution.forward_ic import backfill_factor_ic
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    backfill_outcomes(session, store, as_of)
    backfill_factor_ic(session, store, as_of)


def run_all() -> bool:
    ok = True
    for step in (step_quotes, step_qlib, step_tracklist,
                 step_select, step_debate, step_mark, step_attribution):
        try:
            step()
        except Exception:                       # noqa: BLE001 — 单步失败不阻断
            ok = False
            traceback.print_exc()
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
