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
from app.db.models import Position, DiscoveryPick, Account
from app.data.prices import DictPriceProvider, latest_close
from app.trading.broker import PaperBroker
from app.decision.graph import DecisionGraph
from app.decision.brief import build_brief
from app.decision.llm import LocalClaudeClient, DeepSeekClient, UsageLimitError
from app.reporting.daily_summary import build_daily_summary
from app.attribution.forward_ic import latest_rolling_rank_ic
from app.portfolio.rebalance import is_rebalance_day
from app.portfolio.execute import rebalance_portfolio

PY = sys.executable


def _llm(s):
    if s.decision_llm == "deepseek":
        return DeepSeekClient(s.deepseek_api_key, s.deepseek_base_url, s.deepseek_model)
    return LocalClaudeClient(bin_path=s.claude_bin, model=s.claude_model)


def _session():
    return make_session_factory(make_engine())()


def step_quotes() -> None:
    subprocess.run([PY, str(ROOT / "scripts" / "daily_update_quotes.py")],
                   cwd=ROOT, check=True)


def step_qlib() -> None:
    s = get_settings()
    subprocess.run([PY, str(ROOT / "scripts" / "build_qlib_data.py"),
                    "--qlib-dir", s.qlib_data_dir], cwd=ROOT, check=True)


def step_health() -> None:
    """数据健康检查(DB 缺天/空值/价格/因子 + qlib 与 DB 一致性);FAIL 抛错让本步标红,
    但不阻断后面的选股(daily_full 各步独立)。"""
    subprocess.run([PY, str(ROOT / "scripts" / "check_data_health.py")], cwd=ROOT, check=True)


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


def _retry_on_usage_limit(fn, retries: int = 6, wait_s: int = 1800, sleep=time.sleep):
    """claude 账号限额(UsageLimitError)时长等重试:限额按时段重置(观测过
    22:00 跑时距重置还有约3小时),每 30 分钟试一次共 6 次可跨过;仍限额则抛出,
    让当步标失败——绝不能把限额提示当分析写库(2026-07-06 事故)。"""
    for attempt in range(retries + 1):
        try:
            return fn()
        except UsageLimitError as exc:
            if attempt == retries:
                raise
            print(f"USAGE_LIMIT_WAIT {exc}; {wait_s}s 后重试"
                  f"({attempt + 1}/{retries})", flush=True)
            sleep(wait_s)


def _lowrisk_thesis(closes):
    if len(closes) < 5:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    vol_ann = (var ** 0.5) * (252 ** 0.5) * 100        # 年化波动率(%)
    return (f"低风险异象因子选出:近期日收益年化波动率约{vol_ann:.0f}%(偏低)、"
            f"走势清淡。入选理由是低波动/低换手/低流动性特征,请评估其作为稳健"
            f"低波标的的持有价值(平稳缩量、无暴涨暴跌)。")


def _as_of_for_rebalance(store) -> "date":
    return store.trading_dates(date.today(), 1)[0]


def step_rebalance() -> None:
    s = get_settings()
    session = _session()
    store = QuoteStore(session)
    as_of = _as_of_for_rebalance(store)
    if not is_rebalance_day(as_of, s.rebalance_weekday):
        print(f"REBALANCE_SKIP 非再平衡日 {as_of}(weekday={as_of.weekday()})", flush=True)
        return
    top_date = session.scalar(select(func.max(DiscoveryPick.as_of)))
    if top_date != as_of:
        raise RuntimeError(
            f"step_rebalance: 无当日选股产物(最新={top_date}, 期望={as_of})")
    ranking = [(r.code, r.rank) for r in session.scalars(
        select(DiscoveryPick).where(DiscoveryPick.as_of == top_date)
        .order_by(DiscoveryPick.rank)).all()]
    if not ranking:
        raise RuntimeError("step_rebalance: 无 DiscoveryPick 产物")
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
    if off and not already_recorded(session, "RISK_OFF", as_of):
        record_action(session, "RISK_OFF", as_of, {"reason": off_reason},
                      f"风控停买:{off_reason}")
    if weak_list and not already_recorded(session, "WEAK_SELL", as_of):
        record_action(session, "WEAK_SELL", as_of, {"codes": weak_list},
                      f"持仓弱因子标卖候选:{weak_list}")

    # ── 数据增强:基本面/财报/研报(全部 fail-soft,取不到照常辩论)────────
    from app.data.fundamentals import build_fundamentals
    from app.research.store import ResearchStore, research_as_dict
    research_store = ResearchStore(session)
    try:
        # 2026-09 tushare 到期:财报/增速改 baostock 季频表(同一对象兼具两接口)
        from app.data.baostock_financials import BaostockFinancials
        earnings = financials = BaostockFinancials()
    except Exception as exc:                    # noqa: BLE001
        print(f"FINANCIALS_INIT_SKIP {exc!r}", flush=True)
        earnings = financials = None

    # 预算当晚再平衡辩论池,只给这几只刷新研报
    # ——run_research.py 的口径是全量选股(现在1338只),夜链绝不能按那个跑
    from app.portfolio.rebalance import plan_rebalance
    _sells, _buy_pool = plan_rebalance(ranking, held, topk=s.target_positions,
                                       buffer=s.rebalance_buffer, n_drop=s.rebalance_n_drop)
    pre_candidates = sorted(held | set(_buy_pool))
    try:
        from app.research.sources import EastMoneyNewsSource, CompositeSource
        from app.research.analyzer import ResearchAnalyzer
        from app.research.runner import ResearchRunner
        # tushare 研报(report_rc)随 token 到期下线,只剩东财个股新闻
        _src = CompositeSource([EastMoneyNewsSource()])
        _rr = ResearchRunner(_src, ResearchAnalyzer(_llm(s)), research_store)
        n_research = _rr.run(set(pre_candidates), as_of)
        print(f"RESEARCH_REFRESH candidates={len(pre_candidates)} written={n_research}",
              flush=True)
    except Exception as exc:                    # noqa: BLE001 — 研报失败不挡辩论
        print(f"RESEARCH_REFRESH_SKIP {exc!r}", flush=True)

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
            # 低风险策略视角只挂给买入候选(非持仓);持仓的去留另有逻辑
            strategy = None if h else _lowrisk_thesis(closes)
            fundamentals = build_fundamentals(session, code, as_of, earnings=earnings)
            fin = financials.summary(code) if financials is not None else None
            research = research_as_dict(research_store.latest(code), as_of)
            out.append(build_brief(code, closes, factors, fundamentals, holding,
                                   research=research, financials=fin,
                                   strategy=strategy, recent_volumes=volumes))
        return out

    def _equity_of():
        acc = session.get(Account, 1)
        mv = sum(p.shares * (latest_close(store, p.code, as_of) or 0.0)
                 for p in holds.values())
        return (acc.cash if acc else 0.0) + mv

    def _attempt():
        session.rollback()
        return rebalance_portfolio(
            session, as_of, ranking, held,
            graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
            broker=PaperBroker(session), brief_builder=brief_builder,
            price_of=lambda c: latest_close(store, c, as_of),
            equity_of=_equity_of, topk=s.target_positions,
            buffer=s.rebalance_buffer, n_drop=s.rebalance_n_drop,
            risk_off=off, account_id=1)

    summary = _retry_on_usage_limit(_attempt)
    print(build_daily_summary(session, as_of, account_id=1), flush=True)
    print(f"REBALANCE_DONE {summary}", flush=True)


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
    steps = (("quotes", step_quotes), ("qlib", step_qlib), ("health", step_health),
             ("tracklist", step_tracklist),
             ("select", step_select), ("rebalance", step_rebalance), ("mark", step_mark),
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
