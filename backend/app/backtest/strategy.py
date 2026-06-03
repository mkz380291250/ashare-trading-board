import pandas as pd

# A股交易成本(可调):买 万3 佣金,卖 万3 佣金 + 千1 印花税
DEFAULT_COST = {"open_cost": 0.0003, "close_cost": 0.0013, "min_cost": 5}


def summarize_report(report_df: pd.DataFrame, analysis_df: pd.DataFrame) -> dict:
    """从 qlib backtest 的 report 与 risk_analysis 结果提取扁平指标 dict。
    report_df: 含每日 'return' 列。analysis_df: index=指标名, 含 'risk' 列。"""
    def metric(name):
        if analysis_df is not None and name in analysis_df.index:
            return float(analysis_df.loc[name, "risk"])
        return None
    rets = report_df["return"] if "return" in report_df else pd.Series(dtype=float)
    cum = float((1.0 + rets).prod() - 1.0) if len(rets) else 0.0
    return {
        "days": int(len(report_df)),
        "cum_return": cum,
        "annualized_return": metric("annualized_return"),
        "information_ratio": metric("information_ratio"),
        "max_drawdown": metric("max_drawdown"),
    }


def run_strategy_backtest(score_frame: pd.DataFrame, *, start, end,
                          topk: int = 8, n_drop: int = 2,
                          benchmark: str = "SH000300",
                          account: float = 1e8, cost: dict | None = None) -> dict:
    """用 qlib TopkDropoutStrategy + backtest 跑策略,返回 summarize_report 的 dict。
    需先 init_qlib()。集成细节(executor/exchange kwargs)在冒烟任务联调确定。"""
    from qlib.contrib.strategy import TopkDropoutStrategy
    from qlib.backtest import backtest
    from qlib.contrib.evaluate import risk_analysis

    cost = cost or DEFAULT_COST
    strategy = TopkDropoutStrategy(signal=score_frame["score"],
                                   topk=topk, n_drop=n_drop)
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
    report_normal, _positions = portfolio_metric_dict["1day"]
    excess = report_normal["return"] - report_normal["bench"]
    analysis = risk_analysis(excess, freq="day")
    return summarize_report(report_normal, analysis)
