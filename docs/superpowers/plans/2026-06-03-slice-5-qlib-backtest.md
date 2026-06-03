# 切片5(回测) qlib 策略回测 + 因子分析 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 qlib 原生引擎统一回测系统现有信号(以沪深300为基准),并对因子做 IC/分层分析,复用线上 MomentumProvider/DiscoveryScorer 不重写信号逻辑。

**Architecture:** 新模块 `backend/app/backtest/`:symbols(代码↔qlib符号)、qlib_data(QuoteStore→CSV→dump_bin→init)、scores(逐日跑 scorer 出 qlib score 帧)、factor(自算 IC/RankIC/分层)、strategy(qlib TopkDropoutStrategy 回测+指标解析)。纯逻辑 TDD 单测;qlib bin 构建与 qlib 回测调用由小样本冒烟验证。

**Tech Stack:** Python 3.11, qlib 0.9.7(已装,backtest/strategy/risk_analysis API 可用),pandas, tushare, pytest。qlib 的 `dump_bin.py` 不随 pip 分发,需从 GitHub v0.9.7 vendor 进仓库(fire/loguru 已装)。

工作目录:`backend/`。测试:`.venv/bin/python -m pytest`。分支:`slice-5-backtest`(已创建,基于 main,含切片0-4)。所有纯逻辑测试用 synthetic data,不碰 qlib/网络;qlib 集成只在 Task 5 冒烟。

已确认的代码事实:
- `QuoteStore(session)`:`get_bars(code, start, end) -> list[DailyBar]`(升序)、`get_range(start, end) -> list[DailyQuote]`、`trading_dates(end, limit) -> list[date]`。
- `DailyBar`:`code, trade_date, open, high, low, close, volume, adj_factor`(不复权价+因子;复权 close = close*adj_factor)。
- `app/data/qlib_store.py`:`bars_to_dataframe(bars)` 出列 `[date,open,high,low,close,volume,factor]`。
- `app/discovery/scorer.py`:`DiscoveryScorer(top_n, weights)`,`score(factors)` 返回 `[(code, total, {factor:raw})]` 截断 top_n。
- `app/discovery/snapshot.py`:`QuoteStoreMarketHistory(store).load(as_of, window) -> {code: StockData}`。
- `app/discovery/providers.py`:`MomentumProvider().compute(snapshot) -> {factor:{code:val}}`。
- qlib `pip` 包无 dump_bin;`from qlib.contrib.strategy import TopkDropoutStrategy`、`from qlib.backtest import backtest`、`from qlib.contrib.evaluate import risk_analysis` 均可 import。

---

### Task 1: 代码 ↔ qlib 符号映射

**Files:**
- Create: `app/backtest/__init__.py`(空)
- Create: `app/backtest/symbols.py`
- Test: `tests/test_backtest_symbols.py`(新建)

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_backtest_symbols.py`:

```python
import pytest
from app.backtest.symbols import to_qlib_symbol, from_qlib_symbol


def test_to_qlib_symbol_sh_sz_bj():
    assert to_qlib_symbol("600519.SH") == "SH600519"
    assert to_qlib_symbol("000001.SZ") == "SZ000001"
    assert to_qlib_symbol("920128.BJ") == "BJ920128"


def test_from_qlib_symbol_roundtrip():
    for code in ["600519.SH", "000001.SZ", "920128.BJ"]:
        assert from_qlib_symbol(to_qlib_symbol(code)) == code


def test_invalid_raises():
    with pytest.raises(ValueError):
        to_qlib_symbol("600519")        # 无交易所后缀
    with pytest.raises(ValueError):
        from_qlib_symbol("600519.SH")   # 不是 qlib 符号
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_symbols.py -v`
Expected: FAIL（ModuleNotFoundError: app.backtest.symbols）

- [ ] **Step 3: 实现** — 新建空 `app/backtest/__init__.py`,新建 `app/backtest/symbols.py`:

```python
_EXCHANGES = {"SH", "SZ", "BJ"}


def to_qlib_symbol(code: str) -> str:
    """600519.SH -> SH600519"""
    if "." not in code:
        raise ValueError(f"not a market code: {code}")
    num, ex = code.split(".", 1)
    ex = ex.upper()
    if ex not in _EXCHANGES:
        raise ValueError(f"unknown exchange in {code}")
    return f"{ex}{num}"


def from_qlib_symbol(sym: str) -> str:
    """SH600519 -> 600519.SH"""
    ex = sym[:2].upper()
    if ex not in _EXCHANGES or len(sym) <= 2:
        raise ValueError(f"not a qlib symbol: {sym}")
    return f"{sym[2:]}.{ex}"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_symbols.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/backtest/__init__.py app/backtest/symbols.py tests/test_backtest_symbols.py
git commit -m "feat(backtest): code <-> qlib symbol mapping"
```

---

### Task 2: DiscoveryScorer.score_all（不截断,回归保护 score）

**Files:**
- Modify: `app/discovery/scorer.py`
- Test: `tests/test_discovery_scorer.py`（追加）

说明:回测要全市场排序,不能被 top_n 截断。新增 `score_all(factors)` 返回全量;把 `score()` 改为 `score_all()[:top_n]`(行为不变,现有 scorer 测试回归锁定)。

- [ ] **Step 1: 写失败测试** — 追加到 `tests/test_discovery_scorer.py`:

```python
def test_score_all_returns_full_universe_untruncated():
    factors = {"f1": {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}}
    full = DiscoveryScorer(top_n=2).score_all(factors)
    assert [p[0] for p in full] == ["d", "c", "b", "a"]   # 全量,降序,不截断
    # score() 仍按 top_n 截断(回归)
    assert [p[0] for p in DiscoveryScorer(top_n=2).score(factors)] == ["d", "c"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_discovery_scorer.py::test_score_all_returns_full_universe_untruncated -v`
Expected: FAIL（AttributeError: score_all）

- [ ] **Step 3: 实现** — 在 `app/discovery/scorer.py` 的 `DiscoveryScorer` 类中,把现有 `score` 方法重构为:`score_all` 承载原逻辑(去掉末尾 `[: self.top_n]`),`score` 调 `score_all` 再截断。即:

```python
    def score_all(self, factors: dict[str, dict[str, float]]):
        """同 score() 但不按 top_n 截断,返回全市场 (code, total, raw) 降序。"""
        if not factors:
            return []
        names = list(factors.keys())
        weights = self.weights or {n: 1.0 / len(names) for n in names}
        pct = {n: percentile_rank(factors[n]) for n in names}
        universe: set[str] = set()
        for n in names:
            universe |= set(factors[n])
        scored = []
        for code in universe:
            total = sum(weights.get(n, 0.0) * pct[n].get(code, 0.5) for n in names)
            raw = {n: factors[n][code] for n in names if code in factors[n]}
            scored.append((code, total, raw))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def score(self, factors: dict[str, dict[str, float]]):
        """全市场打分后截断到 top_n。"""
        return self.score_all(factors)[: self.top_n]
```

(把原 `score` 方法体整体替换为上面两个方法。`percentile_rank` 与 `__init__` 不变。)

- [ ] **Step 4: 跑测试确认通过** — 含现有 scorer 全部测试(回归):

Run: `.venv/bin/python -m pytest tests/test_discovery_scorer.py -v`
Expected: PASS（含原有 test_scorer_ranks_and_truncates / test_scorer_weights / 并集回归 等全绿）

- [ ] **Step 5: 提交**

```bash
git add app/discovery/scorer.py tests/test_discovery_scorer.py
git commit -m "feat(discovery): DiscoveryScorer.score_all (untruncated, score() unchanged)"
```

---

### Task 3: scores.py — 逐日组装 qlib score 帧

**Files:**
- Create: `app/backtest/scores.py`
- Test: `tests/test_backtest_scores.py`（新建）

说明:`build_score_frame(dates, factor_fn, scorer)` 解耦 —— `factor_fn(d) -> {factor:{code:val}}`(生产里包 `MarketHistory.load`+providers;测试注入假函数)。输出 MultiIndex `(datetime, instrument)` 单列 `score` 的 DataFrame,instrument 用 qlib 符号。空日(factor_fn 返 {})跳过。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_backtest_scores.py`:

```python
from datetime import date
import pandas as pd
from app.discovery.scorer import DiscoveryScorer
from app.backtest.scores import build_score_frame


def test_build_score_frame_shape_and_symbols():
    # 两天,每天两只票;factor_fn 直接给因子
    data = {
        date(2026, 6, 1): {"mom": {"600519.SH": 0.3, "000001.SZ": 0.1}},
        date(2026, 6, 2): {"mom": {"600519.SH": 0.2, "000001.SZ": 0.4}},
    }
    df = build_score_frame(list(data), lambda d: data[d], DiscoveryScorer(top_n=8))
    assert list(df.index.names) == ["datetime", "instrument"]
    assert df.shape == (4, 1) and "score" in df.columns
    # instrument 用 qlib 符号
    insts = set(df.index.get_level_values("instrument"))
    assert insts == {"SH600519", "SZ000001"}
    # 单因子时 score = 百分位 rank(pct);两只 -> 1.0 / 0.5,高的更高
    s = df.xs(pd.Timestamp(2026, 6, 1), level="datetime")["score"]
    assert s["SH600519"] > s["SZ000001"]


def test_build_score_frame_skips_empty_days():
    data = {date(2026, 6, 1): {}, date(2026, 6, 2): {"mom": {"600519.SH": 0.1}}}
    df = build_score_frame(list(data), lambda d: data[d], DiscoveryScorer(top_n=8))
    assert len(df) == 1
    assert df.index.get_level_values("datetime")[0] == pd.Timestamp(2026, 6, 2)


def test_build_score_frame_empty_when_no_data():
    df = build_score_frame([date(2026, 6, 1)], lambda d: {}, DiscoveryScorer())
    assert df.empty
    assert list(df.index.names) == ["datetime", "instrument"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_scores.py -v`
Expected: FAIL（ModuleNotFoundError: app.backtest.scores）

- [ ] **Step 3: 实现** — 新建 `app/backtest/scores.py`:

```python
import pandas as pd
from app.backtest.symbols import to_qlib_symbol


def build_score_frame(dates, factor_fn, scorer) -> pd.DataFrame:
    """对每个交易日用 factor_fn 取因子、scorer.score_all 全市场打分,
    汇成 MultiIndex (datetime, instrument) 单列 'score' 的 DataFrame。
    factor_fn(d) 返回 {factor: {code: value}};返回 {} 的日子跳过。"""
    rows = []
    for d in dates:
        factors = factor_fn(d)
        if not factors:
            continue
        for code, total, _raw in scorer.score_all(factors):
            rows.append((pd.Timestamp(d), to_qlib_symbol(code), total))
    idx = pd.MultiIndex.from_tuples(
        [(r[0], r[1]) for r in rows] or [],
        names=["datetime", "instrument"])
    return pd.DataFrame({"score": [r[2] for r in rows]}, index=idx)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_scores.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/backtest/scores.py tests/test_backtest_scores.py
git commit -m "feat(backtest): build_score_frame (per-day scorer -> qlib score frame)"
```

---

### Task 4: factor.py — 前向收益 + IC/RankIC/分层

**Files:**
- Create: `app/backtest/factor.py`
- Test: `tests/test_backtest_factor.py`（新建）

说明:两块纯 math。① `build_forward_returns(dates, codes, adj_close_fn)`:对每个 (date_i, code) 算次日复权收益 `adj_close(date_{i+1})/adj_close(date_i)-1`(最后一天无次日→跳过)。`adj_close_fn(d, code) -> float|None`。② `factor_report(score_frame, fwd_returns, layers=5)`:按日截面算 IC(Pearson)、RankIC(Spearman),取均值与 IR(均值/标准差);并按分位分 N 层出每层平均前向收益。fwd_returns 是 MultiIndex (datetime, instrument) 的 Series。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_backtest_factor.py`:

```python
from datetime import date
import pandas as pd
from app.backtest.factor import build_forward_returns, factor_report


def test_build_forward_returns_next_day_adj():
    prices = {  # adj close
        (date(2026, 6, 1), "SH600519"): 100.0, (date(2026, 6, 2), "SH600519"): 110.0,
        (date(2026, 6, 1), "SZ000001"): 50.0,  (date(2026, 6, 2), "SZ000001"): 45.0,
    }
    fr = build_forward_returns([date(2026, 6, 1), date(2026, 6, 2)],
                               ["SH600519", "SZ000001"],
                               lambda d, c: prices.get((d, c)))
    # 只有 6/1 有次日收益;6/2 无次日 -> 不在结果里
    assert abs(fr.loc[(pd.Timestamp(2026, 6, 1), "SH600519")] - 0.10) < 1e-9
    assert abs(fr.loc[(pd.Timestamp(2026, 6, 1), "SZ000001")] + 0.10) < 1e-9
    assert pd.Timestamp(2026, 6, 2) not in fr.index.get_level_values("datetime")


def test_factor_report_ic_perfect_positive():
    # 单日:score 与次日收益完全同序 -> IC=RankIC=1
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp(2026, 6, 1), s) for s in ["A", "B", "C", "D"]],
        names=["datetime", "instrument"])
    score = pd.DataFrame({"score": [1.0, 2.0, 3.0, 4.0]}, index=idx)
    fwd = pd.Series([0.01, 0.02, 0.03, 0.04], index=idx)
    rep = factor_report(score, fwd, layers=2)
    assert abs(rep["ic_mean"] - 1.0) < 1e-9
    assert abs(rep["rank_ic_mean"] - 1.0) < 1e-9
    # 高分层(layer 1)前向收益高于低分层(layer 0)
    assert rep["layer_returns"][-1] > rep["layer_returns"][0]


def test_factor_report_handles_single_name_day():
    # 截面只有 1 只票当天无法算相关 -> 跳过该日,不抛
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp(2026, 6, 1), "A")], names=["datetime", "instrument"])
    rep = factor_report(pd.DataFrame({"score": [1.0]}, index=idx),
                        pd.Series([0.01], index=idx), layers=2)
    assert rep["ic_mean"] == 0.0 or rep["days"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_factor.py -v`
Expected: FAIL（ModuleNotFoundError: app.backtest.factor）

- [ ] **Step 3: 实现** — 新建 `app/backtest/factor.py`:

```python
import pandas as pd


def build_forward_returns(dates, codes, adj_close_fn) -> pd.Series:
    """次日复权收益:adj_close(d+1)/adj_close(d)-1,按 (datetime, instrument)。
    dates 升序;最后一天无次日,跳过。缺价(None)跳过该 (d,code)。"""
    dates = sorted(dates)
    out = {}
    for i in range(len(dates) - 1):
        d, nxt = dates[i], dates[i + 1]
        for c in codes:
            p0 = adj_close_fn(d, c)
            p1 = adj_close_fn(nxt, c)
            if p0 and p1 and p0 != 0:
                out[(pd.Timestamp(d), c)] = p1 / p0 - 1.0
    idx = pd.MultiIndex.from_tuples(list(out) or [],
                                    names=["datetime", "instrument"])
    return pd.Series(list(out.values()), index=idx, dtype="float64")


def factor_report(score_frame: pd.DataFrame, fwd_returns: pd.Series,
                  layers: int = 5) -> dict:
    """按日截面算 IC(Pearson)/RankIC(Spearman) 及其 IR,并分 N 层均收益。"""
    s = score_frame["score"]
    joined = pd.DataFrame({"score": s, "ret": fwd_returns}).dropna()
    ics, rics = [], []
    for _, g in joined.groupby(level="datetime"):
        if len(g) < 2 or g["score"].nunique() < 2 or g["ret"].nunique() < 2:
            continue
        ics.append(g["score"].corr(g["ret"]))
        rics.append(g["score"].corr(g["ret"], method="spearman"))
    layer_means = _layer_returns(joined, layers)
    n = len(ics)
    ic = pd.Series(ics)
    ric = pd.Series(rics)
    return {
        "days": n,
        "ic_mean": float(ic.mean()) if n else 0.0,
        "ic_ir": float(ic.mean() / ic.std()) if n > 1 and ic.std() else 0.0,
        "rank_ic_mean": float(ric.mean()) if n else 0.0,
        "rank_ic_ir": float(ric.mean() / ric.std()) if n > 1 and ric.std() else 0.0,
        "layer_returns": layer_means,
    }


def _layer_returns(joined: pd.DataFrame, layers: int) -> list:
    """每日按 score 分 layers 层(0=最低分),返回各层跨日平均前向收益。"""
    buckets = {i: [] for i in range(layers)}
    for _, g in joined.groupby(level="datetime"):
        if len(g) < layers:
            continue
        ranks = g["score"].rank(method="first")
        lab = ((ranks - 1) / len(g) * layers).astype(int).clip(0, layers - 1)
        for lyr, sub in g["ret"].groupby(lab):
            buckets[int(lyr)].append(sub.mean())
    return [float(pd.Series(v).mean()) if v else 0.0
            for i, v in sorted(buckets.items())]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_factor.py -v`
Expected: PASS（3 个）

- [ ] **Step 5: 提交**

```bash
git add app/backtest/factor.py tests/test_backtest_factor.py
git commit -m "feat(backtest): forward returns + IC/RankIC/layered factor report"
```

---

### Task 5: strategy.py — qlib 回测指标解析（解析逻辑单测,qlib 调用封装）

**Files:**
- Create: `app/backtest/strategy.py`
- Test: `tests/test_backtest_strategy.py`（新建）

说明:`run_strategy_backtest` 直接调 qlib(集成由 Task 6 冒烟验证)。本任务**只单测可测部分**:把"从 qlib 的 report DataFrame 提取指标"拆成纯函数 `summarize_report(report_df, analysis_df)`,用 synthetic DataFrame 测。`run_strategy_backtest` 自身组装 qlib 调用 + 调 `summarize_report`,不在单测覆盖(无 qlib 数据)。

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_backtest_strategy.py`:

```python
import pandas as pd
from app.backtest.strategy import summarize_report


def test_summarize_report_extracts_metrics():
    # 模拟 qlib backtest 的 report_normal:含 return / bench 列
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    report = pd.DataFrame({"return": [0.01, -0.02, 0.03],
                           "bench": [0.005, -0.01, 0.01]}, index=idx)
    # 模拟 risk_analysis 输出(qlib 返回 index=指标名, 列 'risk')
    analysis = pd.DataFrame(
        {"risk": [0.15, 1.2, -0.08]},
        index=["annualized_return", "information_ratio", "max_drawdown"])
    out = summarize_report(report, analysis)
    assert abs(out["annualized_return"] - 0.15) < 1e-9
    assert abs(out["information_ratio"] - 1.2) < 1e-9
    assert abs(out["max_drawdown"] + 0.08) < 1e-9
    assert out["days"] == 3
    assert abs(out["cum_return"] - ((1.01 * 0.98 * 1.03) - 1.0)) < 1e-6


def test_summarize_report_missing_metric_is_none():
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    report = pd.DataFrame({"return": [0.0], "bench": [0.0]}, index=idx)
    analysis = pd.DataFrame({"risk": [0.1]}, index=["annualized_return"])
    out = summarize_report(report, analysis)
    assert out["annualized_return"] == 0.1
    assert out["information_ratio"] is None   # 缺失 -> None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_strategy.py -v`
Expected: FAIL（ModuleNotFoundError: app.backtest.strategy）

- [ ] **Step 3: 实现** — 新建 `app/backtest/strategy.py`:

```python
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
```

注:`run_strategy_backtest` 的 qlib 参数(executor class / exchange_kwargs / `portfolio_metric_dict["1day"]` 键名)以 qlib 0.9.7 实际为准,Task 6 冒烟时校正;`summarize_report` 是被单测锁定的纯函数。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_strategy.py -v`
Expected: PASS（2 个）

- [ ] **Step 5: 提交**

```bash
git add app/backtest/strategy.py tests/test_backtest_strategy.py
git commit -m "feat(backtest): qlib strategy backtest + summarize_report (parsing unit-tested)"
```

---

### Task 6: qlib_data.py + vendored dump_bin + 数据脚本 + 小样本冒烟

**Files:**
- Create: `app/backtest/qlib_data.py`
- Create: `scripts/vendor/__init__.py`(空) + `scripts/vendor/dump_bin.py`（vendor 自 qlib v0.9.7）
- Create: `scripts/build_qlib_data.py`
- Create: `scripts/run_backtest.py`
- Test: `tests/test_backtest_qlib_data.py`（只测可测的 export/symbol-naming 部分）

说明:这是 qlib 集成 + 数据构建任务。export CSV 逻辑可单测(假 bars);dump_bin/init_qlib/真实回测由小样本冒烟验证。

- [ ] **Step 1: vendor dump_bin.py**

```bash
mkdir -p scripts/vendor && touch scripts/vendor/__init__.py
.venv/bin/python -c "import requests,pathlib; pathlib.Path('scripts/vendor/dump_bin.py').write_text(requests.get('https://raw.githubusercontent.com/microsoft/qlib/v0.9.7/scripts/dump_bin.py', timeout=20).text)"
.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); from vendor.dump_bin import DumpDataAll; print('DumpDataAll import ok')"
```
Expected: `DumpDataAll import ok`

- [ ] **Step 2: 写失败测试** — 新建 `tests/test_backtest_qlib_data.py`:

```python
from datetime import date
from app.data.source import DailyBar
from app.backtest.qlib_data import export_bars_csv


def _bars():
    return [DailyBar("600519.SH", date(2026, 6, 1), 100, 105, 99, 104, 1000, 1.0),
            DailyBar("600519.SH", date(2026, 6, 2), 104, 108, 103, 107, 1200, 1.0)]


def test_export_bars_csv_uses_qlib_symbol_filename(tmp_path):
    path = export_bars_csv(_bars(), str(tmp_path))
    assert path.name == "SH600519.csv"      # 文件名是 qlib 符号
    text = path.read_text()
    assert "date,open,high,low,close,volume,factor" in text
    assert "104" in text


def test_export_bars_csv_empty_returns_none(tmp_path):
    assert export_bars_csv([], str(tmp_path)) is None
```

- [ ] **Step 3: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_qlib_data.py -v`
Expected: FAIL（ModuleNotFoundError: app.backtest.qlib_data）

- [ ] **Step 4: 实现** — 新建 `app/backtest/qlib_data.py`:

```python
from pathlib import Path
from app.data.qlib_store import bars_to_dataframe
from app.backtest.symbols import to_qlib_symbol

_QLIB_INITED = False


def export_bars_csv(bars, out_dir: str):
    """把一只票的 bars 写成 qlib 符号命名的 CSV(date/o/h/l/c/volume/factor)。
    空 bars -> None。"""
    if not bars:
        return None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df = bars_to_dataframe(bars)
    path = out / f"{to_qlib_symbol(bars[0].code)}.csv"
    df.to_csv(path, index=False)
    return path


def export_market_csvs(store, codes, start, end, out_dir: str) -> int:
    """逐 code 从 QuoteStore 取 bars 写 CSV。返回成功写出的只数。"""
    n = 0
    for code in codes:
        bars = store.get_bars(code, start, end)
        if export_bars_csv(bars, out_dir) is not None:
            n += 1
    return n


def export_csi300_csv(pro, start, end, out_dir: str):
    """tushare index_daily(000300.SH) -> CSV(符号 SH000300, factor=1.0)。"""
    import pandas as pd
    df = pro.index_daily(ts_code="000300.SH",
                         start_date=start.strftime("%Y%m%d"),
                         end_date=end.strftime("%Y%m%d"))
    if df is None or getattr(df, "empty", True):
        return None
    df = df.sort_values("trade_date")
    out_df = pd.DataFrame({
        "date": pd.to_datetime(df["trade_date"]),
        "open": df["open"], "high": df["high"], "low": df["low"],
        "close": df["close"], "volume": df["vol"], "factor": 1.0})
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / "SH000300.csv"
    out_df.to_csv(path, index=False)
    return path


def build_bin(csv_dir: str, qlib_dir: str) -> None:
    """调 vendored DumpDataAll 把 CSV 目录转成 qlib bin 库。"""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from vendor.dump_bin import DumpDataAll
    DumpDataAll(csv_path=csv_dir, qlib_dir=qlib_dir, freq="day",
                date_field_name="date").dump()


def init_qlib(qlib_dir: str) -> None:
    """qlib.init(provider_uri, region=cn)。幂等。"""
    global _QLIB_INITED
    if _QLIB_INITED:
        return
    if not Path(qlib_dir).exists():
        raise FileNotFoundError(
            f"qlib data not found at {qlib_dir}; run scripts/build_qlib_data.py first")
    import qlib
    qlib.init(provider_uri=qlib_dir, region="cn")
    _QLIB_INITED = True
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_qlib_data.py -v`
Expected: PASS（2 个)

- [ ] **Step 6: 写数据脚本** — 新建 `scripts/build_qlib_data.py`:

```python
import argparse, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.data.quote_store import QuoteStore
from app.backtest.qlib_data import (export_market_csvs, export_csi300_csv, build_bin)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv-dir", default="./data/qlib_csv")
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--limit", type=int, default=0, help=">0 则只导前 N 只(冒烟用)")
    args = p.parse_args()

    s = get_settings()
    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    dates = sorted(session.scalars(select(distinct(DailyQuote.trade_date))).all())
    start, end = dates[0], dates[-1]
    codes = sorted({c for c in session.scalars(select(distinct(DailyQuote.code))).all()})
    if args.limit:
        codes = codes[: args.limit]
    print(f"exporting {len(codes)} stocks {start}..{end}", flush=True)
    n = export_market_csvs(store, codes, start, end, args.csv_dir)
    import tushare as ts
    pro = ts.pro_api(s.tushare_token)
    csi = export_csi300_csv(pro, start, end, args.csv_dir)
    print(f"exported {n} stocks + csi300={csi is not None}; dumping bin...", flush=True)
    build_bin(args.csv_dir, args.qlib_dir)
    print("QLIB_DUMP_DONE", flush=True)


if __name__ == "__main__":
    main()
```

新建 `scripts/run_backtest.py`:

```python
import argparse, sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import distinct, select
from app.config import get_settings
from app.db.database import make_engine, make_session_factory
from app.db.models import DailyQuote
from app.data.quote_store import QuoteStore
from app.discovery.snapshot import QuoteStoreMarketHistory
from app.discovery.providers import MomentumProvider
from app.discovery.scorer import DiscoveryScorer
from app.backtest.qlib_data import init_qlib
from app.backtest.scores import build_score_frame
from app.backtest.factor import build_forward_returns, factor_report
from app.backtest.strategy import run_strategy_backtest
from app.backtest.symbols import to_qlib_symbol, from_qlib_symbol


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--window", type=int, default=20)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    args = p.parse_args()

    session = make_session_factory(make_engine())()
    store = QuoteStore(session)
    hist = QuoteStoreMarketHistory(store)
    prov = MomentumProvider()
    scorer = DiscoveryScorer(top_n=8)

    all_dates = sorted(session.scalars(select(distinct(DailyQuote.trade_date))).all())
    start = date(*map(int, args.start.split("-"))) if args.start else all_dates[args.window]
    end = date(*map(int, args.end.split("-"))) if args.end else all_dates[-1]
    dates = [d for d in all_dates if start <= d <= end]

    def factor_fn(d):
        snap = hist.load(d, args.window)
        return prov.compute(snap) if snap else {}

    score = build_score_frame(dates, factor_fn, scorer)
    print(f"score frame: {len(score)} rows over {len(dates)} days", flush=True)

    # 前向收益:复权 close,从库取
    bars_cache = {}
    def adj_close_fn(d, sym):
        code = from_qlib_symbol(sym)
        if code not in bars_cache:
            bars_cache[code] = {b.trade_date: b.close * b.adj_factor
                                for b in store.get_bars(code, start, end)}
        return bars_cache[code].get(d)

    codes_syms = sorted(set(score.index.get_level_values("instrument")))
    fwd = build_forward_returns(dates, codes_syms, adj_close_fn)
    rep = factor_report(score, fwd)
    print("FACTOR:", rep, flush=True)

    init_qlib(args.qlib_dir)
    bt = run_strategy_backtest(score, start=start, end=end)
    print("STRATEGY:", bt, flush=True)
    print("BACKTEST_DONE", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: 语法校验 + 小样本冒烟**

语法:
```bash
.venv/bin/python -c "import ast; [ast.parse(open(f).read()) for f in ['scripts/build_qlib_data.py','scripts/run_backtest.py','app/backtest/qlib_data.py']]; print('ok')"
```
小样本冒烟(前 30 只股 + 沪深300,真实 dump + qlib 回测;需 ashare.db 已回填、tushare_token 配好):
```bash
.venv/bin/python scripts/build_qlib_data.py --limit 30 --csv-dir /tmp/qlib_csv --qlib-dir /tmp/qlib_cn 2>&1 | tail -5
.venv/bin/python scripts/run_backtest.py --qlib-dir /tmp/qlib_cn 2>&1 | tail -8
```
Expected: `QLIB_DUMP_DONE`;`FACTOR: {...}`(ic 在 [-1,1]、days>0);`STRATEGY: {...}`(annualized_return/information_ratio/max_drawdown 数量级合理);`BACKTEST_DONE`。**若 qlib 回测 kwargs 报错,在此校正 `run_strategy_backtest` 的 executor/exchange/键名,使 `summarize_report` 单测仍绿。** 若沪深300基准在 qlib 中缺失,确认 SH000300 已 dump 进 bin 且 benchmark 名匹配。

- [ ] **Step 8: 全量测试 + 提交**

```bash
.venv/bin/python -m pytest -q     # 全绿
git add app/backtest/qlib_data.py scripts/vendor/ scripts/build_qlib_data.py scripts/run_backtest.py tests/test_backtest_qlib_data.py
git commit -m "feat(backtest): qlib data build (vendored dump_bin) + backtest runner, smoke-verified"
```

---

## 完成标准

- 全量 `pytest -q` 全绿(新增约 13+ 单测)。
- 小样本(30股+沪深300)冒烟:dump_bin 成功、init_qlib 成功、策略回测出年化/夏普/最大回撤/信息比率(基准沪深300)、因子报告出 IC/RankIC/分层收益。
- 复用线上 MomentumProvider/DiscoveryScorer,信号逻辑零重写;`score()` 行为回归不变。
- 分支 `slice-5-backtest`,逐任务提交,待用户决定合并/推送(PAT 见项目记忆)。
- 全量 qlib 库(5700股)经 `scripts/build_qlib_data.py`(无 --limit)后台 setsid 跑(冒烟通过后),非本计划阻塞项。
