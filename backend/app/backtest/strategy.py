import pandas as pd

# A股交易成本(可调):买 万3 佣金,卖 万3 佣金 + 千1 印花税
DEFAULT_COST = {"open_cost": 0.0003, "close_cost": 0.0013, "min_cost": 5}


def to_weekly_signal(score: pd.Series) -> pd.Series:
    """把 (datetime, instrument) 的打分降采样为「每周只在周首个交易日给值」。

    TopkDropout 在没有信号的交易日不调仓(generate_trade_decision 返回空),
    因此只保留每个 ISO 周的首个交易日 → 调仓频率从「每日」真正降到「每周」。
    注意:仅让周内信号持平没用,TopkDropout 每步都会强制 swap n_drop。"""
    names = list(score.index.names)
    df = score.unstack(level=1)            # index=datetime, columns=instrument
    keep = ~df.index.to_period("W").duplicated()   # 每个 ISO 周的首个交易日
    df = df.loc[keep]
    out = df.stack()
    out.index = out.index.set_names(names)
    return out.sort_index()


def _held_set(pos) -> frozenset:
    """从 qlib Position 取当前持有的股票代码集合(剔除 cash 等标量字段)。"""
    d = getattr(pos, "position", pos)
    if not isinstance(d, dict):
        return frozenset()
    return frozenset(k for k, v in d.items() if isinstance(v, dict))


def trade_stats(positions, days: int, report_df: pd.DataFrame) -> dict:
    """从逐日持仓 diff 出实际成交:一次换股(1卖+1买)记 2 笔。
    positions: qlib backtest 返回的 {timestamp: Position}。失败时退回换手率估计。"""
    weeks = max(days / 5.0, 1e-9)
    try:
        items = [positions[k] for k in sorted(positions.keys())]
    except Exception:
        items = None
    if items:
        prev, total, rebal_days = None, 0, 0
        for pos in items:
            held = _held_set(pos)
            if prev is not None:
                diff = len(held ^ prev)   # 对称差 = 当日买入+卖出的笔数
                total += diff
                if diff:
                    rebal_days += 1
            prev = held
        return {
            "trades_total": int(total),
            "trades_per_week": round(total / weeks, 2),
            "rebalance_days": int(rebal_days),
            "weeks": round(weeks, 1),
        }
    # 退路:用 report 的 turnover 估计(无法给出精确笔数)
    to = report_df["turnover"] if "turnover" in report_df else pd.Series(dtype=float)
    return {
        "trades_total": None,
        "trades_per_week": None,
        "rebalance_days": int((to.iloc[1:] > 1e-6).sum()) if len(to) > 1 else 0,
        "weeks": round(weeks, 1),
    }


def summarize_report(report_df: pd.DataFrame, analysis_df: pd.DataFrame) -> dict:
    """从 qlib backtest 的 report 与 risk_analysis 结果提取扁平指标 dict。
    report_df: 含每日 'return' 列。analysis_df: index=指标名, 含 'risk' 列。"""
    def metric(name):
        if analysis_df is not None and name in analysis_df.index:
            return float(analysis_df.loc[name, "risk"])
        return None
    rets = report_df["return"] if "return" in report_df else pd.Series(dtype=float)
    cum = float((1.0 + rets).prod() - 1.0) if len(rets) else 0.0
    to = report_df["turnover"] if "turnover" in report_df else pd.Series(dtype=float)
    return {
        "days": int(len(report_df)),
        "cum_return": cum,
        "annualized_return": metric("annualized_return"),
        "information_ratio": metric("information_ratio"),
        "max_drawdown": metric("max_drawdown"),
        "turnover_daily_mean": float(to.mean()) if len(to) else None,
        "turnover_weekly_mean": float(to.mean() * 5) if len(to) else None,
    }


def run_strategy_backtest(score_frame: pd.DataFrame, *, start, end,
                          topk: int = 8, n_drop: int = 2,
                          benchmark: str = "SH000300",
                          account: float = 1e8, cost: dict | None = None,
                          rebalance: str = "day", hold_thresh: int = 1) -> dict:
    """用 qlib TopkDropoutStrategy + backtest 跑策略,返回 summarize_report 的 dict。
    需先 init_qlib()。

    rebalance: "day" 每日调仓(原行为);"week" 周频调仓(信号周内持平,压低换手)。
    hold_thresh: 最短持有天数,进一步抑制频繁卖出。
    返回 dict 额外含 trades_total / trades_per_week / rebalance_days(实测换手)。"""
    from qlib.contrib.strategy import TopkDropoutStrategy
    from qlib.backtest import backtest
    from qlib.contrib.evaluate import risk_analysis

    cost = cost or DEFAULT_COST
    signal = score_frame["score"]
    if rebalance == "week":
        signal = to_weekly_signal(signal)
    strategy = TopkDropoutStrategy(signal=signal, topk=topk, n_drop=n_drop,
                                   hold_thresh=hold_thresh)
    executor_config = {
        "class": "SimulatorExecutor", "module_path": "qlib.backtest.executor",
        "kwargs": {"time_per_step": "day", "generate_portfolio_metrics": True},
    }
    exchange_kwargs = {
        "freq": "day", "limit_threshold": 0.095,
        "deal_price": "close", "open_cost": cost["open_cost"],
        "close_cost": cost["close_cost"], "min_cost": cost["min_cost"],
    }
    portfolio_metric_dict, _ = backtest(
        start_time=start, end_time=end, strategy=strategy,
        executor=executor_config, benchmark=benchmark, account=account,
        exchange_kwargs=exchange_kwargs)
    report_normal, positions = portfolio_metric_dict["1day"]
    # annualized_return / max_drawdown 取策略自身收益曲线;information_ratio
    # 取超额(策略-基准)曲线 —— 否则前两者会被算成 alpha/超额回撤,名实不符。
    strat = risk_analysis(report_normal["return"], freq="day")
    excess = risk_analysis(report_normal["return"] - report_normal["bench"], freq="day")
    analysis = pd.DataFrame({"risk": {
        "annualized_return": strat.loc["annualized_return", "risk"],
        "max_drawdown": strat.loc["max_drawdown", "risk"],
        "information_ratio": excess.loc["information_ratio", "risk"],
    }})
    out = summarize_report(report_normal, analysis)
    out.update(trade_stats(positions, out["days"], report_normal))
    return out
