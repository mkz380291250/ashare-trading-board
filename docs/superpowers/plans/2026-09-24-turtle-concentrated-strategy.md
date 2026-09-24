# 集中持仓盈亏比策略(海龟式)第一阶段:回测引擎 + 参数扫描 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用独立的逐日事件驱动引擎,在创业板动态池 2015 起数据上扫描"进场 × 退出 × 时间止损"参数网格,2015~2021 选参、2022 起验证,给出集中持仓(3 仓)盈亏比策略能否盈利的结论。

**Architecture:** `app/backtest/turtle.py` 提供纯 numpy 的引擎(`Params`、`run_turtle(panel, params) -> Result`)与指标函数;`app/backtest/turtle_data.py` 从研究库取面板(复权 OHLC、未复权 open/pre_close、score、atr、hi20);`scripts/run_turtle_backtest.py` 组网格、并行跑、选参、写报告。

**Tech Stack:** Python 3.11、numpy、pandas、qlib 0.9.7(只用于取数)、pytest。命令在 `backend/` 下用 `.venv/bin/python`。

**Spec:** `docs/superpowers/specs/2026-09-24-turtle-concentrated-strategy-design.md`

## Global Constraints

- 复权价空间成交与止损止盈;涨跌停判定用未复权 open 与 pre_close,创业板 2020-08-24 起 20%,之前 10%,容差 0.5%。
- 成本 0.15%/边;每仓资金 = 总资产 / slots;100 股整手;每天最多开 1 仓。
- 触发顺序:open≤stop 按 open;low≤stop 按 stop;(固定比例)high≥tp 时 open≥tp 按 open 否则 tp;同日双触按止损;时间止损次日开盘;跌停日不能卖顺延;数据终止按最后收盘。
- 不改生产代码路径;新模块只被新脚本与测试引用。
- 每任务结束 commit,消息结尾附 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 与 `Claude-Session: https://claude.ai/code/session_0187eXhJ1Wt8vLkRJ2Ya7DMK`。

## File Structure

| 文件 | 职责 |
|---|---|
| `app/backtest/turtle.py` (新) | `Params` 数据类、`run_turtle`(引擎)、`metrics(result, bench)`、`Trade`/`Result` |
| `app/backtest/turtle_data.py` (新) | `load_panel(qlib_dir, universe, frozen_path, start, end) -> Panel`(numpy 数组 + 日期/代码索引) |
| `scripts/run_turtle_backtest.py` (新) | 网格、多进程、选参(IS Calmar)、OOS 验证、邻域表、报告 |
| `tests/test_backtest_turtle.py` (新) | 引擎规则与指标测试(合成面板) |

---

### Task 1: 引擎核心 `app/backtest/turtle.py`(TDD)

**Files:** Create `app/backtest/turtle.py`;Test `tests/test_backtest_turtle.py`

**Interfaces (Produces):**
```python
@dataclass(frozen=True)
class Params:
    entry: str = "factor"          # factor | breakout
    exit: str = "fixed"            # fixed | atr
    sl: float = 0.06               # fixed: 止损比例
    rr: float = 2.0                # fixed: 止盈 = sl*rr
    k_stop: float = 2.0            # atr: 初始止损 = entry - k_stop*atr
    k_trail: float = 2.0           # atr: 最高收盘回撤 k_trail*atr
    max_hold: int = 0              # 0=不限
    slots: int = 3
    top_n: int = 30                # breakout: 因子前 N
    cost: float = 0.0015
    cash: float = 1_000_000.0

@dataclass
class Trade: code: str; entry_i: int; entry_px: float; exit_i: int; exit_px: float; shares: int; reason: str  # stop|tp|trail|time|end
@dataclass
class Result: nav: np.ndarray; trades: list[Trade]; exposure: np.ndarray   # 与 dates 对齐

class Panel:  # 全部 (T, N) float32,nan=无数据
    dates: np.ndarray[datetime64]; codes: list[str]
    open, high, low, close: np.ndarray         # 复权
    raw_open, raw_pre_close: np.ndarray        # 未复权
    score: np.ndarray; atr: np.ndarray; hi20: np.ndarray
    limit: np.ndarray  # (T,N) 涨跌停幅 0.1/0.2

def run_turtle(panel: Panel, p: Params) -> Result
def metrics(res: Result, dates, bench_ret: np.ndarray | None) -> dict   # ann/mdd/calmar/sharpe/win_rate/avg_win_loss/profit_factor/n_trades/avg_hold/exposure/excess_ann
```

- [ ] **Step 1: 写失败测试(合成 3 只票 × 30 天)**

```python
import numpy as np, pandas as pd, pytest
from app.backtest.turtle import Panel, Params, run_turtle, metrics

def _panel(T=30, N=3, price=None):
    dates = pd.bdate_range("2024-01-01", periods=T).values
    z = np.full((T, N), np.nan, dtype="float32")
    close = np.tile(np.linspace(10, 10, T)[:, None], (1, N)).astype("float32") if price is None else price
    p = Panel(dates=dates, codes=[f"S{i}" for i in range(N)],
              open=close.copy(), high=close * 1.01, low=close * 0.99, close=close,
              raw_open=close.copy(), raw_pre_close=np.vstack([close[:1], close[:-1]]),
              score=np.tile(np.array([3., 2., 1.], dtype="float32"), (T, 1)),
              atr=np.full((T, N), 0.2, dtype="float32"), hi20=close * 0.98,
              limit=np.full((T, N), 0.2, dtype="float32"))
    return p

def test_entry_next_open_and_one_per_day():
    p = _panel()
    res = run_turtle(p, Params(slots=3, exit="fixed", sl=0.5, rr=100))   # 永不触发
    ent = sorted(t.entry_i for t in res.trades)
    assert ent == [1, 2, 3]                     # 第 0 天信号 → 第 1 天开盘成交;每天 1 仓;3 槽满
    assert [t.code for t in sorted(res.trades, key=lambda t: t.entry_i)] == ["S0", "S1", "S2"]
    assert all(t.reason == "end" for t in res.trades)

def test_fixed_stop_gap_open_vs_intraday():
    p = _panel()
    p.low[5, 0] = 9.3                            # 盘中触及 6% 止损(entry 10 → 9.4)
    p.open[10, 1] = 9.0; p.low[10, 1] = 8.9      # 跳空低开穿过止损
    res = run_turtle(p, Params(slots=2, sl=0.06, rr=100))
    t0 = next(t for t in res.trades if t.code == "S0"); t1 = next(t for t in res.trades if t.code == "S1")
    assert t0.exit_i == 5 and t0.exit_px == pytest.approx(9.4) and t0.reason == "stop"
    assert t1.exit_i == 10 and t1.exit_px == pytest.approx(9.0)

def test_fixed_tp_and_same_day_both_prefers_stop():
    p = _panel()
    p.high[6, 0] = 11.5                          # tp = 10*(1+0.06*2)=11.2
    p.high[8, 1] = 11.5; p.low[8, 1] = 9.0       # 同日双触 → 止损
    res = run_turtle(p, Params(slots=2, sl=0.06, rr=2))
    t0 = next(t for t in res.trades if t.code == "S0"); t1 = next(t for t in res.trades if t.code == "S1")
    assert t0.reason == "tp" and t0.exit_px == pytest.approx(11.2)
    assert t1.reason == "stop" and t1.exit_px == pytest.approx(9.4)

def test_atr_trailing_moves_up():
    p = _panel()
    p.close[3:8, 0] = 12.0; p.high[3:8, 0] = 12.1; p.low[3:8, 0] = 11.9   # 涨到 12,最高收盘 12
    p.low[9, 0] = 11.5                            # 12 - 2*0.2 = 11.6 → 触发 trail
    res = run_turtle(p, Params(slots=1, exit="atr", k_stop=2, k_trail=2))
    t = res.trades[0]
    assert t.reason == "trail" and t.exit_i == 9 and t.exit_px == pytest.approx(11.6)

def test_time_stop_next_open_and_limit_down_defers():
    p = _panel()
    p.raw_open[4, 0] = 8.0; p.raw_pre_close[4, 0] = 10.0   # 第 4 天跌停开盘,不能卖
    res = run_turtle(p, Params(slots=1, sl=0.5, rr=100, max_hold=2))
    t = res.trades[0]
    assert t.entry_i == 1 and t.exit_i == 5 and t.reason == "time"   # 3 日到期→第 4 天想卖被跌停顺延→第 5 天开盘

def test_limit_up_open_skips_entry_and_delisting_exits_last_close():
    p = _panel()
    p.raw_open[1, 0] = 12.0; p.raw_pre_close[1, 0] = 10.0    # S0 一字涨停买不到 → 当天买不到,次日再选
    p.close[15:, 1] = np.nan; p.open[15:, 1] = np.nan; p.high[15:, 1] = np.nan; p.low[15:, 1] = np.nan
    res = run_turtle(p, Params(slots=1, sl=0.5, rr=100))
    first = min(res.trades, key=lambda t: t.entry_i)
    assert first.entry_i == 1 and first.code == "S1"                 # 涨停跳过 S0,同一天选下一名? 否:每天只尝试 1 只 → 第 1 天空仓
    # 上面断言按设计改为:第 1 天尝试 S0 失败不再补;第 2 天再选(S0 仍最高分,已可买)
    
def test_metrics_basic():
    p = _panel()
    p.high[6, 0] = 11.5
    res = run_turtle(p, Params(slots=1, sl=0.06, rr=2))
    m = metrics(res, p.dates, None)
    assert m["n_trades"] >= 1 and 0 <= m["win_rate"] <= 1 and m["ann"] > 0 and m["mdd"] <= 0
```
> 注:最后一个涨停测试按设计定稿为"当天尝试失败不补,次日重选",断言写成 `first.entry_i == 2 and first.code == "S0"`。

- [ ] **Step 2: 跑测试确认失败** — `.venv/bin/python -m pytest tests/test_backtest_turtle.py -q` → ImportError。

- [ ] **Step 3: 实现引擎**

要点(逐日循环 t=0..T−1):
1. 先处理持仓退出(用第 t 天数据):对每个持仓 h(entry_i < t):
   - 若 h.pending_exit(时间止损或前日跌停顺延):若今日非跌停开盘 → 按 open[t] 出,reason 保留;否则继续顺延。
   - 计算 stop:fixed → entry×(1−sl);atr → max(entry−k_stop×atr_entry, highest_close−k_trail×atr_entry)(highest_close 用到 t−1 为止的收盘;当日 close 更新在退出判断之后)。
   - 若 open[t] ≤ stop → 出 open;elif low[t] ≤ stop → 出 stop(reason "stop",若 atr 且 stop 来自 trailing 则 "trail");elif fixed 且 high[t] ≥ tp → 出 max(open[t], tp) reason "tp"。
   - 跌停开盘(raw_open ≤ raw_pre_close×(1−limit+0.005))时不能卖:标 pending 顺延(止损止盈也顺延)。
   - 否则更新 highest_close = max(., close[t]);持有天数 +1;若 max_hold>0 且天数 ≥ max_hold → pending_exit("time")。
   - close[t] 为 nan(退市/终止)→ 按最后一个非 nan close 出,reason "end"。
2. 再执行前一日的开仓意向(entry_intent = code 选于 t−1):若 open[t] 有值且非一字涨停(raw_open ≥ raw_pre_close×(1+limit−0.005) 视为涨停)→ 按 open[t] 买,shares = floor(cash_per_slot/open/100)×100,扣成本;失败则丢弃。
3. 收盘后生成意向(若有空位):factor → score[t] 有值、非持仓、close 非 nan 中 argmax;breakout → score 前 top_n 中 close[t] > hi20[t] 的取 score 最高。
4. nav[t] = cash + Σ shares×close[t](nan 用最后价);exposure[t] = 持仓市值/nav。
   最后一天强平所有持仓 reason "end"。
`metrics`:ann = nav[-1]^(243/T)−1;mdd;calmar;sharpe(日收益);win_rate;avg_win_loss = 均盈利率/均亏损率;profit_factor = Σ盈/Σ亏(按金额);n_trades;avg_hold;exposure 均值;excess_ann(相对 bench_ret 累计)。

- [ ] **Step 4: 跑测试通过** — 7 passed。
- [ ] **Step 5: Commit** — `feat(turtle): 集中持仓盈亏比回测引擎`。

---

### Task 2: 取数 `app/backtest/turtle_data.py`

**Files:** Create `app/backtest/turtle_data.py`;Test 追加到 `tests/test_backtest_turtle.py`(只测 `panel_from_frames`,不连 qlib)。

**Interfaces:** `panel_from_frames(px: pd.DataFrame, score: pd.DataFrame) -> Panel`(px: MultiIndex(datetime,instrument) 列 open/high/low/close/factor/pre_close/hi20_raw;内部算复权、atr、hi20、limit)、`load_panel(qlib_dir, universe, frozen_path, start, end) -> Panel`。

- [ ] Step 1 测试:2 只票 5 天手工数据,断言复权 = raw×factor、atr 第 1 天 nan、hi20 为前 20 日最高(短窗用 min_periods=1)、limit 2020-08-24 前 0.1 后 0.2、缺票日 nan。
- [ ] Step 2 实现:qlib 字段 `$open,$high,$low,$close,$factor,Ref($close,1),Max(Ref($high,1),20)`;score 用 `composite_score(to_datetime_instrument(...), signs, weights)`;取数起点 = start − 60 交易日以便 ATR/hi20 热身,返回时裁到 start。ATR 用复权 TR 的 20 日 `rolling(min_periods=20)`。
- [ ] Step 3 冒烟:`load_panel("data/qlib_cn_full","cyb_dyn","data/factors/frozen_composite.json","2024-01-01","2024-03-31")` 形状 (≈58, ≈1300)。
- [ ] Step 4 Commit — `feat(turtle): 研究库取数与面板构建`。

---

### Task 3: 扫描脚本 `scripts/run_turtle_backtest.py`

- [ ] Step 1 写脚本:参数 `--universe cyb_dyn --frozen a,b --start 2015-01-05 --split 2022-01-01 --slots 3 --workers 3 --grid full|small --bench 399006.SZ`。网格按 spec(84 组/每套因子)。每组:`run_turtle` 全窗一次,按 split 切 nav 与 trades 分别算 IS/OOS 指标(IS 期用 nav[:split] 归一,OOS 用 nav[split:]/nav[split] 归一;trades 按 entry_i 归属)。多进程 `ProcessPoolExecutor(workers)`(Panel 用全局变量在 fork 后共享)。
- [ ] Step 2 选参与报告:IS 剔除 n_trades<30,按 calmar 降序取前 5,输出 OOS 指标;最优参数邻域表(sl±0.02 / rr 相邻 / k_trail 另一档 / max_hold 三档);结论按 spec 标准判定"可用/不可用";全网格表按 OOS calmar 排序附在 json。写 `data/reports/turtle_backtest_<date>.{json,md}` 与 `docs/reports/turtle_backtest_<date>.md`。
- [ ] Step 3 冒烟:`--grid small --start 2024-01-01 --split 2025-01-01` 秒级跑完。
- [ ] Step 4 全量后台跑两套 frozen;记录耗时。
- [ ] Step 5 Commit — `feat(turtle): 参数扫描与报告脚本`。

---

### Task 4: 结论与汇报

- [ ] 读报告,核对最优组的交易明细抽样(前 10 笔),确认没有异常价(如 exit_px 远离当日高低区间)。
- [ ] 向用户汇报:两套因子分的 IS/OOS 最优组、邻域稳定性、是否达标、与现有 15 只策略同窗对比(年化/回撤/Calmar),并给第二阶段建议。

## Self-Review
- Spec 覆盖:引擎规则(Task 1)、数据/宇宙/ATR/hi20/涨跌停(Task 2)、网格/选参/报告(Task 3)、结论(Task 4);第二阶段不在本计划。
- 类型一致:`Panel`/`Params`/`Result` 在 Task 1 定义,Task 2/3 复用;`metrics` 签名一致。
