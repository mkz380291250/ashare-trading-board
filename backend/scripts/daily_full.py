"""每日编排:全市场行情 -> qlib 重建 -> 跟踪表指标刷新。
可命令行运行(python scripts/daily_full.py),也被 APScheduler 调用 run_all()。"""
import subprocess
import sys
import time
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
from app.attribution.forward_ic import latest_rolling_rank_ic

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
    from app.policy.rules import is_risk_off, weak_holdings
    from app.policy.guardrails import record_action, already_recorded
    off, off_reason = is_risk_off(session, as_of, dd_stop=s.dd_stop,
                                  hitrate_stop=s.hitrate_stop)
    weak_list = weak_holdings(session, held, as_of, pctl=s.weak_pctl,
                              consecutive=s.weak_consecutive)
    weak = set(weak_list)
    target = len(held) if off else s.target_positions
    if off and not already_recorded(session, "RISK_OFF", as_of):
        record_action(session, "RISK_OFF", as_of, {"reason": off_reason},
                      f"风控停买:{off_reason}")
    if weak_list and not already_recorded(session, "WEAK_SELL", as_of):
        record_action(session, "WEAK_SELL", as_of, {"codes": weak_list},
                      f"持仓弱因子标卖候选:{weak_list}")

    def _reversal_thesis(closes):
        if len(closes) < 5:
            return None
        last, ma = closes[-1], sum(closes) / len(closes)
        hi = max(closes)
        below = (1 - last / ma) * 100 if ma else 0.0
        dd = (1 - last / hi) * 100 if hi else 0.0
        return (f"短周期反转(超跌反弹)因子选出:现价{last}低于均线约{below:.0f}%、"
                f"近期自高点回撤约{dd:.0f}%。下跌本身是入选理由,请评估反弹胜算"
                f"(缩量止跌/跌速衰竭/企稳),而非要求已处上涨趋势。")

    def brief_builder(codes):
        start = date(as_of.year - 1, as_of.month, as_of.day)
        out = []
        for code in codes:
            bars = store.get_bars(code, start, as_of)
            closes = [b.close for b in bars][-20:]
            volumes = [b.volume for b in bars][-20:]
            h = holds.get(code)
            holding = {"shares": h.shares, "cost": h.cost} if h else None
            factors = {"weak_factor": True} if code in weak else {}
            # 反转策略视角只挂给买入候选(非持仓);持仓的去留另有逻辑
            strategy = None if h else _reversal_thesis(closes)
            out.append(build_brief(code, closes, factors, {}, holding,
                                   strategy=strategy, recent_volumes=volumes))
        return out

    from app.decision.trend import is_uptrend
    _trend_start = date(as_of.year - 1, as_of.month, as_of.day)

    def buy_filter(code):
        if s.buy_trend_window <= 0:
            return True
        closes = [b.close for b in store.get_bars(code, _trend_start, as_of)]
        return is_uptrend(closes, window=s.buy_trend_window, tol=s.buy_trend_tol)

    summary = run_daily_decisions(
        session, as_of, ranking, held, graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
        brief_builder=brief_builder, broker=PaperBroker(session),
        price_of=lambda c: latest_close(store, c, as_of),
        target=target, quality_pctl=s.quality_pctl,
        min_confidence=s.min_confidence, max_debate=s.max_debate, account_id=1,
        buy_filter=buy_filter)
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


def step_policy() -> None:
    from app.policy.rules import factor_decayed
    from app.policy.guardrails import record_action, already_recorded
    from app.policy.actions import run_remine
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = store.trading_dates(date.today(), 1)[0]
    notes = []
    if (factor_decayed(session, as_of, window=s.ic_decay_window,
                       consecutive=s.ic_decay_consecutive, threshold=s.ic_decay_threshold)
            and not already_recorded(session, "REMINE", as_of)):
        ric = latest_rolling_rank_ic(session, as_of=as_of, window=s.ic_decay_window)
        if s.policy_auto_remine:
            rc = run_remine()
            status = "AUTO" if rc == 0 else "FAILED"
            detail = ("因子衰减→自动重挖换产物(旧产物已归档 data/factors/archive/)"
                      if rc == 0 else f"因子衰减→重挖失败 rc={rc}")
            record_action(session, "REMINE", as_of, {"rolling_rank_ic": ric, "rc": rc},
                          detail, status=status)
            notes.append(f"因子衰减→重挖 rc={rc}")
        else:
            record_action(session, "REMINE", as_of, {"rolling_rank_ic": ric},
                          "因子衰减→待人工确认重挖", status="PENDING")
            notes.append("因子衰减→待确认重挖")
    print(f"POLICY_DONE {as_of} " + ("; ".join(notes) if notes else "无动作"), flush=True)


def run_all() -> bool:
    import json
    from datetime import datetime
    from app.db.models import SchedulerRun
    steps = (("quotes", step_quotes), ("qlib", step_qlib), ("tracklist", step_tracklist),
             ("select", step_select), ("debate", step_debate), ("mark", step_mark),
             ("attribution", step_attribution), ("policy", step_policy))
    session = _session()
    run = SchedulerRun(as_of=date.today(), started_at=datetime.now(), ok=False, detail="[]")
    session.add(run)
    session.commit()
    results = []
    ok = True
    for name, step in steps:
        try:
            step()
            results.append({"step": name, "ok": True, "error": ""})
        except Exception as exc:                # noqa: BLE001 — 单步失败不阻断
            ok = False
            results.append({"step": name, "ok": False, "error": repr(exc)[:300]})
            traceback.print_exc()
    run.finished_at = datetime.now()
    run.ok = ok
    run.detail = json.dumps(results, ensure_ascii=False)
    for attempt in range(3):                    # 收尾写库撞锁重试,保证 UI 状态必落
        try:
            session.commit()
            break
        except Exception:                       # noqa: BLE001 — database is locked 等
            session.rollback()
            if attempt == 2:
                traceback.print_exc()
            else:
                time.sleep(15)
    print(f"RUN_DONE {run.as_of} ok={ok} " +
          ("; ".join(r["step"] for r in results if not r["ok"]) or "全部成功"), flush=True)
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
