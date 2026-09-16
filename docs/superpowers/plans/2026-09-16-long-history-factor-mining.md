# 长历史多周期因子重检 + 新家族扩库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 2010 起的长历史在独立研究库上按 7 个 regime 重检现有 48 因子,新增财务/资金流/分红家族,升级为按族去相关 + IR 加权的复合因子,并经验证闸与同窗回测决定是否替换生产 frozen。

**Architecture:** 研究库 `data/qlib_cn_full`(2010 起,由 `build_qlib_data.py --start --extra` 导出,PIT 财务/资金流字段由 `app/quant/pit_fields.py` 从 `tushare_extra.db` 生成后 merge 进每票 CSV)+ 动态宇宙 `cyb_dyn`;新脚本 `run_factor_regimes.py` 出逐年/逐 regime RankIC 报告;`factor_mine.py` 扩两个因子字典与族映射;`factor_compose.py`/`frozen.py` 支持加权与族上限去重。生产 `data/qlib_cn` 与夜链不动。

**Tech Stack:** Python 3 (`backend/.venv/bin/python`), qlib 0.9.7, pandas 2.3, sqlite3(标准库,读 `data/tushare_extra.db`), SQLAlchemy(读 `ashare.db`), pytest。

**Spec:** `docs/superpowers/specs/2026-09-16-long-history-factor-mining-design.md`

## Global Constraints

- 所有命令在 `backend/` 下执行,解释器用 `.venv/bin/python`;测试 `.venv/bin/python -m pytest tests -q`(基线 408 通过)。
- 生产 `data/qlib_cn`、夜链 `daily_full.py`、`frozen_composite.json` 在第 10 任务之前不得改动。
- 研究库路径固定 `./data/qlib_cn_full`,CSV 目录 `./data/qlib_csv_full`;`data/` 已在 gitignore。
- PIT 规则:交易日 d 可用财报 = `ann_date <= d` 中 ann_date 最新的一份;同 ann_date 取 end_date 最新;发布前 NaN。
- 单位:`$total_mv/$circ_mv` 万元,`$amount` 千元,资金流 `mf_*` 万元,财报金额 元,比率类 %。
- qlib 表达式只用 `Ref/Mean/Std/Max/Min/Abs/Log/Greater/If/Le` 等已有算子。
- 每个任务结束 commit,commit message 结尾附:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 与 `Claude-Session: https://claude.ai/code/session_0187eXhJ1Wt8vLkRJ2Ya7DMK`。
- 与用户交互:第 6 任务结束是检查点 1(给用户看 regime 报告);第 10 任务结束是检查点 2(用户拍板是否替换 frozen)。

## File Structure

| 文件 | 职责 |
|---|---|
| `app/config.py` | 新增 `qlib_research_dir` |
| `app/quant/pit_fields.py` (新) | 从 tushare_extra.db 读四表/分红/资金流,产出每票日频 PIT 附加列 |
| `app/backtest/qlib_data.py` | `export_market_csvs_full` 增 `extra_fn` 钩子,merge 附加列 |
| `scripts/build_qlib_data.py` | `--start`、`--extra` 参数 |
| `app/quant/universe.py` | `dynamic_rows` + `write_instrument_rows` |
| `scripts/build_universe.py` | `--dynamic --qlib-dir --prefix` |
| `app/quant/factor_regimes.py` (新) | REGIMES 常量、逐 regime/逐年聚合、全周期稳健判定、md 渲染 |
| `scripts/run_factor_regimes.py` (新) | 编排:研究库取数 → 聚合 → 报告 |
| `app/quant/factor_mine.py` | `FUNDAMENTAL_FACTORS`/`FLOW_FACTORS`/`FACTOR_FAMILY`,`required_fields` |
| `scripts/run_factor_mining.py` | `--qlib-dir`,缺字段跳过,默认长窗 |
| `app/quant/factor_compose.py` | `composite_score(..., weights=None)`、`dedup_by_family`、`ir_weights` |
| `app/factors/frozen.py` | `select_frozen(..., family_cap, ir_map)` |
| `app/discovery/qlib_provider.py` | `score_panel` 传 weights |
| `scripts/freeze_factors.py` | `--qlib-dir`、`--candidates`(regime 报告交集)、族去相关、IR 权重 |
| `scripts/run_composite_backtest.py` | `--qlib-dir`、`--frozen`(直接回测某 frozen 文件) |
| `tests/test_pit_fields.py` / `test_universe_dynamic.py` / `test_factor_regimes.py` / `test_quant_factor_compose.py` / `test_frozen_select.py` / `test_factor_mine.py` | 对应测试 |

---

## Phase A — 研究库、动态宇宙、多 regime 重检(检查点 1)

### Task 1: 配置 + 导出脚本参数(`--start` / `--qlib-dir` 研究库)

**Files:**
- Modify: `app/config.py:18`
- Modify: `scripts/build_qlib_data.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.qlib_research_dir: str = "./data/qlib_cn_full"`;`build_qlib_data.py --start YYYY-MM-DD --csv-dir X --qlib-dir Y [--extra]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加:

```python
def test_qlib_research_dir_default():
    from app.config import Settings
    assert Settings(_env_file=None).qlib_research_dir == "./data/qlib_cn_full"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_qlib_research_dir_default -q`
Expected: FAIL `AttributeError: 'Settings' object has no attribute 'qlib_research_dir'`

- [ ] **Step 3: 实现**

`app/config.py` 在 `qlib_export_start` 一行之后加:

```python
    qlib_research_dir: str = "./data/qlib_cn_full"  # 研究库(2010 起 + PIT 财务/资金流字段),
                                                    # 由 build_qlib_data.py --start 2010-01-01 --extra 手动重建,不进夜链
```

`scripts/build_qlib_data.py` 的 `main()` 改为:

```python
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv-dir", default="./data/qlib_csv")
    p.add_argument("--qlib-dir", default="./data/qlib_cn")
    p.add_argument("--limit", type=int, default=0, help=">0 则只导前 N 只(冒烟用)")
    p.add_argument("--start", default="", help="覆盖 settings.qlib_export_start(研究库用 2010-01-01)")
    p.add_argument("--extra", action="store_true",
                   help="附加 PIT 财务/分红/资金流字段(读 data/tushare_extra.db)")
    args = p.parse_args()

    s = get_settings()
    session = make_session_factory(make_engine())()
    dates = sorted(session.scalars(select(distinct(DailyQuote.trade_date))).all())
    start, end = dates[0], dates[-1]
    export_start = date.fromisoformat(args.start or s.qlib_export_start)
    if start < export_start:
        start = export_start
    codes = sorted({c for c in session.scalars(select(distinct(DailyQuote.code))).all()})
    if args.limit:
        codes = codes[: args.limit]
    extra_fn = None
    if args.extra:
        from app.quant.pit_fields import PitFields
        pit = PitFields("./data/tushare_extra.db")
        extra_fn = pit.for_code
    print(f"exporting {len(codes)} stocks {start}..{end} extra={args.extra}", flush=True)
    n = export_market_csvs_full(session, codes, start, end, args.csv_dir, extra_fn=extra_fn)
    from app.data.baostock_source import BaostockSource
    src = BaostockSource()
    csi = export_csi300_csv(src, start, end, args.csv_dir)
    src.close()
    print(f"exported {n} stocks + csi300={csi is not None}; dumping bin...", flush=True)
    build_bin(args.csv_dir, args.qlib_dir)
    print("QLIB_DUMP_DONE", flush=True)
```

(`PitFields` 与 `extra_fn` 在 Task 2/3 实现;本任务先让 `--extra` 分支存在,不带 `--extra` 时行为与原来一致。)

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py scripts/build_qlib_data.py tests/test_config.py
git commit -m "feat(research): qlib_research_dir 配置 + build_qlib_data --start/--extra 参数"
```

---

### Task 2: PIT 财务/分红/资金流字段生成 `app/quant/pit_fields.py`

**Files:**
- Create: `app/quant/pit_fields.py`
- Test: `tests/test_pit_fields.py`

**Interfaces:**
- Produces:
  - `quarterly_derive(inc: pd.DataFrame, cf: pd.DataFrame, bs: pd.DataFrame, fi: pd.DataFrame) -> pd.DataFrame`:输入四表(列见下),输出按 `ann_date` 排序的季频表,列 `ann_date,end_date,np_ttm,rev_ttm,ocf_ttm,sue,q_roe,gm,q_sales_yoy,q_profit_yoy,profit_acc,accrual,debt_to_assets,total_assets`。
  - `align_pit(quarterly: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame`:index=dates,含上述列(不含 ann_date/end_date)+ `ann_age`。
  - `dps_ttm(div: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series`。
  - `moneyflow_daily(mf: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame` 列 `mf_lg_net,mf_sm_net,mf_net`。
  - `class PitFields(db_path)`:`.for_code(code: str, dates: pd.DatetimeIndex) -> pd.DataFrame`(index=dates,全部附加列;任何缺失都给 NaN 列)。`PIT_COLS` 常量 = 全部附加列名列表。

- [ ] **Step 1: 写失败测试**

`tests/test_pit_fields.py`:

```python
import numpy as np
import pandas as pd
import pytest
from app.quant.pit_fields import (
    quarterly_derive, align_pit, dps_ttm, moneyflow_daily, PitFields, PIT_COLS)


def _inc(rows):
    return pd.DataFrame(rows, columns=["ann_date", "end_date", "revenue", "n_income_attr_p"])


def test_ttm_uses_single_quarter_diffs_across_year_boundary():
    # 2024Q1..2025Q1 的 ytd 净利:10,25,45,70 | 2025Q1=15
    inc = _inc([
        ("20240425", "20240331", 100.0, 10.0),
        ("20240820", "20240630", 220.0, 25.0),
        ("20241028", "20240930", 350.0, 45.0),
        ("20250328", "20241231", 500.0, 70.0),
        ("20250426", "20250331", 130.0, 15.0),
    ])
    empty = pd.DataFrame()
    q = quarterly_derive(inc, empty, empty, empty)
    # 单季:10,15,20,25,15 → 2025Q1 TTM = 15+20+25+15 = 75
    last = q.iloc[-1]
    assert last["end_date"] == "20250331"
    assert last["np_ttm"] == pytest.approx(75.0)
    assert last["rev_ttm"] == pytest.approx(130 + 120 + 130 + 150)
    # 前三季不足 4 个单季 → TTM NaN
    assert np.isnan(q.iloc[0]["np_ttm"]) and np.isnan(q.iloc[2]["np_ttm"])
    assert q.iloc[3]["np_ttm"] == pytest.approx(70.0)


def test_sue_is_yoy_diff_over_std_of_diffs():
    # 单季净利恒等差:每季比去年同季多 2,历史 8 季差全为 2 → std=0 → NaN;
    # 最后一季差改为 6,前 8 季 std>0 → 有值
    rows, ytd = [], 0.0
    vals = [1, 2, 3, 4, 3, 4, 5, 6, 5, 6, 7, 8, 7, 8, 9, 14]  # 单季
    for i, v in enumerate(vals):
        yr = 2021 + i // 4
        qn = i % 4
        ytd = v if qn == 0 else ytd + v
        end = f"{yr}{['0331','0630','0930','1231'][qn]}"
        rows.append((end, end, 0.0, ytd))
    q = quarterly_derive(_inc(rows), pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    assert q.iloc[-1]["sue"] > 3.0          # 最后一季 yoy 差=6,历史差全为 2,std 极小 → 大 SUE
    assert np.isnan(q.iloc[4]["sue"])       # 不足 8 季历史


def test_align_pit_no_lookahead_and_restatement_wins_by_ann_date():
    q = pd.DataFrame({
        "ann_date": ["20250428", "20250428", "20250830"],
        "end_date": ["20250331", "20241231", "20250630"],   # 同 ann_date 两份:取 end_date 最新
        "q_roe": [5.0, 99.0, 7.0], "gm": [30.0, 31.0, 32.0],
    })
    dates = pd.to_datetime(["2025-04-25", "2025-04-28", "2025-04-29", "2025-08-29", "2025-09-01"])
    out = align_pit(q, dates)
    assert np.isnan(out.loc["2025-04-25", "q_roe"])         # 公告前 NaN
    assert out.loc["2025-04-28", "q_roe"] == 5.0             # 同 ann_date 取 end_date 最新
    assert out.loc["2025-08-29", "q_roe"] == 5.0
    assert out.loc["2025-09-01", "q_roe"] == 7.0
    assert out.loc["2025-04-28", "ann_age"] == 0
    assert out.loc["2025-04-29", "ann_age"] == 1
    assert out.loc["2025-08-29", "ann_age"] == 3             # 4/28,4/29,8/29 → 第 3 个交易日
    assert np.isnan(out.loc["2025-04-25", "ann_age"])


def test_dps_ttm_window_by_ex_date():
    div = pd.DataFrame({
        "div_proc": ["实施", "实施", "预案"],
        "ex_date": ["20240610", "20250605", "20250701"],
        "cash_div_tax": [1.0, 2.0, 9.0],
    })
    dates = pd.to_datetime(["2024-06-09", "2024-06-10", "2025-06-04", "2025-06-05", "2025-06-11", "2025-07-02"])
    s = dps_ttm(div, dates)
    assert s.loc["2024-06-09"] == 0.0
    assert s.loc["2024-06-10"] == 1.0
    assert s.loc["2025-06-04"] == 1.0                        # 365 天内仍算
    assert s.loc["2025-06-05"] == 3.0
    assert s.loc["2025-06-11"] == 2.0                        # 2024-06-10 已出窗
    assert s.loc["2025-07-02"] == 2.0                        # 预案不算


def test_moneyflow_daily_units():
    mf = pd.DataFrame({
        "trade_date": ["20250102"], "buy_sm_amount": [10.0], "sell_sm_amount": [4.0],
        "buy_lg_amount": [100.0], "sell_lg_amount": [30.0],
        "buy_elg_amount": [50.0], "sell_elg_amount": [20.0], "net_mf_amount": [7.0],
    })
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    out = moneyflow_daily(mf, dates)
    assert out.loc["2025-01-02", "mf_lg_net"] == 100.0       # (100+50)-(30+20)
    assert out.loc["2025-01-02", "mf_sm_net"] == 6.0
    assert out.loc["2025-01-02", "mf_net"] == 7.0
    assert np.isnan(out.loc["2025-01-03", "mf_lg_net"])      # 无数据日不 ffill


def test_pitfields_missing_code_gives_nan_columns(tmp_path):
    import sqlite3
    db = tmp_path / "x.db"
    con = sqlite3.connect(db)
    for t, cols in [("ts_income", "ts_code,ann_date,end_date,revenue,n_income_attr_p"),
                    ("ts_cashflow", "ts_code,ann_date,end_date,n_cashflow_act"),
                    ("ts_balancesheet", "ts_code,ann_date,end_date,total_assets"),
                    ("ts_fina_indicator", "ts_code,ann_date,end_date,q_roe,grossprofit_margin,q_sales_yoy,q_profit_yoy,debt_to_assets"),
                    ("ts_dividend", "ts_code,div_proc,ex_date,cash_div_tax"),
                    ("ts_moneyflow", "ts_code,trade_date,buy_sm_amount,sell_sm_amount,buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount,net_mf_amount")]:
        con.execute(f"create table {t} ({cols})")
    con.commit(); con.close()
    pit = PitFields(str(db))
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    out = pit.for_code("000001.SZ", dates)
    assert list(out.columns) == PIT_COLS
    assert len(out) == 2
    assert out.isna().all().all()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_pit_fields.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'app.quant.pit_fields'`

- [ ] **Step 3: 实现 `app/quant/pit_fields.py`**

```python
"""Point-in-time(PIT)附加字段:从 tushare_extra.db 的季频四表/分红/资金流
生成每只票"每交易日一行"的研究字段,供 qlib 研究库导出 merge。

对齐规则:交易日 d 可用的财报 = ann_date<=d 中 ann_date 最新的一份(同 ann_date
取 end_date 最新);向前填充;公告前 NaN。任何表缺失 → 对应列全 NaN,不抛错。
单位:金额 元;比率 %;资金流 万元。"""
import sqlite3
import numpy as np
import pandas as pd

Q_ENDS = ("0331", "0630", "0930", "1231")

QUARTERLY_COLS = ["np_ttm", "rev_ttm", "ocf_ttm", "sue", "q_roe", "gm",
                  "q_sales_yoy", "q_profit_yoy", "profit_acc", "accrual",
                  "debt_to_assets", "total_assets"]
PIT_COLS = QUARTERLY_COLS + ["ann_age", "dps_ttm", "mf_lg_net", "mf_sm_net", "mf_net"]


def _latest_per_end(df: pd.DataFrame) -> pd.DataFrame:
    """同 end_date 多份(重述)只留 ann_date 最早的一份做「单季/TTM」序列基础
    (序列派生需要每季唯一值;重述通过 align_pit 的 ann_date 逻辑另行处理)。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else [])
    d = df.dropna(subset=["end_date"]).copy()
    d["ann_date"] = d["ann_date"].fillna(d["end_date"])
    d = d.sort_values(["end_date", "ann_date"]).drop_duplicates("end_date", keep="first")
    return d.reset_index(drop=True)


def _single_quarter(ytd: pd.Series, end_dates: pd.Series) -> pd.Series:
    """ytd 累计 → 单季:Q1 = 自身;其余 = 本期 − 上一期(上一期须是同年前一季,否则 NaN)。"""
    out = []
    prev_end, prev_val = None, np.nan
    for e, v in zip(end_dates, ytd):
        yr, md = e[:4], e[4:]
        if md == "0331":
            out.append(v)
        else:
            want = yr + Q_ENDS[Q_ENDS.index(md) - 1]
            out.append(v - prev_val if prev_end == want else np.nan)
        prev_end, prev_val = e, v
    return pd.Series(out, index=ytd.index, dtype="float64")


def _ttm(single: pd.Series, end_dates: pd.Series) -> pd.Series:
    """最近 4 个连续单季之和;不连续/不足 → NaN。"""
    ends = list(end_dates)
    out = []
    for i in range(len(single)):
        if i < 3:
            out.append(np.nan); continue
        ok = all(_next_q(ends[j]) == ends[j + 1] for j in range(i - 3, i))
        vals = single.iloc[i - 3:i + 1]
        out.append(float(vals.sum()) if ok and not vals.isna().any() else np.nan)
    return pd.Series(out, index=single.index, dtype="float64")


def _next_q(end: str) -> str:
    yr, md = int(end[:4]), end[4:]
    k = Q_ENDS.index(md)
    return f"{yr}{Q_ENDS[k + 1]}" if k < 3 else f"{yr + 1}{Q_ENDS[0]}"


def _sue(single: pd.Series, end_dates: pd.Series) -> pd.Series:
    """(q_t − q_{t−4}) / std(最近 8 个 yoy 差,不含当期)。同季匹配按 end_date 字符串。"""
    by_end = dict(zip(end_dates, single))
    diffs = []
    for e, v in zip(end_dates, single):
        prev = by_end.get(f"{int(e[:4]) - 1}{e[4:]}")
        diffs.append(v - prev if prev is not None and pd.notna(prev) and pd.notna(v) else np.nan)
    d = pd.Series(diffs, index=single.index, dtype="float64")
    hist_std = d.shift(1).rolling(8, min_periods=8).std()
    return d / hist_std.replace(0.0, np.nan)


def quarterly_derive(inc, cf, bs, fi) -> pd.DataFrame:
    """四表 → 季频派生表(按 ann_date 升序;同一季的重述行保留,ann_date 不同)。
    inc: ann_date,end_date,revenue,n_income_attr_p;cf: ...,n_cashflow_act;
    bs: ...,total_assets;fi: ...,q_roe,grossprofit_margin,q_sales_yoy,q_profit_yoy,debt_to_assets。"""
    base = _latest_per_end(inc) if inc is not None and not inc.empty else pd.DataFrame(
        columns=["ann_date", "end_date", "revenue", "n_income_attr_p"])
    out = pd.DataFrame({"end_date": base["end_date"].astype(str)})
    if len(out):
        np_q = _single_quarter(base["n_income_attr_p"].astype(float), out["end_date"])
        rev_q = _single_quarter(base["revenue"].astype(float), out["end_date"])
        out["np_ttm"] = _ttm(np_q, out["end_date"])
        out["rev_ttm"] = _ttm(rev_q, out["end_date"])
        out["sue"] = _sue(np_q, out["end_date"])
    else:
        out["np_ttm"] = out["rev_ttm"] = out["sue"] = np.nan

    def _merge(df, cols):
        nonlocal out
        if df is None or df.empty:
            for c in cols:
                out[c] = np.nan
            return
        d = _latest_per_end(df)[["end_date"] + cols]
        d["end_date"] = d["end_date"].astype(str)
        out = out.merge(d, on="end_date", how="outer").sort_values("end_date").reset_index(drop=True)

    _merge(cf, ["n_cashflow_act"])
    if out["n_cashflow_act"].notna().any():
        ocf_q = _single_quarter(out["n_cashflow_act"].astype(float), out["end_date"])
        out["ocf_ttm"] = _ttm(ocf_q, out["end_date"])
    else:
        out["ocf_ttm"] = np.nan
    _merge(bs, ["total_assets"])
    _merge(fi, ["q_roe", "grossprofit_margin", "q_sales_yoy", "q_profit_yoy", "debt_to_assets"])
    out = out.rename(columns={"grossprofit_margin": "gm"})
    out["profit_acc"] = out["q_profit_yoy"].astype(float).diff()
    # accrual 用 ytd 口径:(ytd 净利 − ytd 经营现金流)/总资产
    ytd_np = base.set_index(base["end_date"].astype(str))["n_income_attr_p"].astype(float) if len(base) else pd.Series(dtype=float)
    out["accrual"] = (out["end_date"].map(ytd_np) - out["n_cashflow_act"].astype(float)) / out["total_assets"].astype(float).replace(0.0, np.nan)

    # ann_date:各表最早公告日中取「该季首次公告」= 各表 ann_date 的最小值;重述行(同 end_date 更晚 ann_date)
    # 由 _restatements 追加
    ann = pd.concat([_ann(inc), _ann(cf), _ann(bs), _ann(fi)]).groupby("end_date")["ann_date"].min()
    out["ann_date"] = out["end_date"].map(ann).fillna(out["end_date"])
    out = out.sort_values(["ann_date", "end_date"]).reset_index(drop=True)
    cols = ["ann_date", "end_date"] + QUARTERLY_COLS
    for c in cols:
        if c not in out.columns:
            out[c] = np.nan
    return out[cols]


def _ann(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["end_date", "ann_date"])
    d = df[["end_date", "ann_date"]].dropna().copy()
    d["end_date"] = d["end_date"].astype(str)
    d["ann_date"] = d["ann_date"].astype(str)
    return d


def align_pit(quarterly: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """季频表 → 日频 PIT 面板(index=dates)。同 ann_date 多份取 end_date 最新;
    ann_age = 距最近公告的交易日数(公告日=0),公告前 NaN。"""
    cols = [c for c in quarterly.columns if c not in ("ann_date", "end_date")]
    if quarterly.empty:
        out = pd.DataFrame(np.nan, index=dates, columns=cols)
        out["ann_age"] = np.nan
        return out
    q = quarterly.copy()
    q["ann_date"] = pd.to_datetime(q["ann_date"].astype(str), format="%Y%m%d", errors="coerce")
    q = q.dropna(subset=["ann_date"]).sort_values(["ann_date", "end_date"])
    q = q.drop_duplicates("ann_date", keep="last").set_index("ann_date")
    out = q[cols].reindex(q.index.union(dates)).ffill().reindex(dates)
    # ann_age
    ann_dates = q.index
    pos = ann_dates.searchsorted(dates, side="right") - 1        # 最近公告的序号
    ages = np.full(len(dates), np.nan)
    if len(ann_dates):
        last_ann = ann_dates[np.clip(pos, 0, len(ann_dates) - 1)]
        # 距离 = 交易日序号差:公告日若非交易日,以其后第一个交易日为 0
        first_td = dates.searchsorted(last_ann, side="left")
        ages = np.arange(len(dates)) - first_td
        ages = ages.astype(float)
        ages[pos < 0] = np.nan
    out["ann_age"] = ages
    return out


def dps_ttm(div: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    """过去 365 天(含当日)内 ex_date<=d 的已实施税前每股现金分红之和。"""
    if div is None or div.empty:
        return pd.Series(0.0, index=dates)
    d = div[div["div_proc"] == "实施"].dropna(subset=["ex_date"]).copy()
    d["ex_date"] = pd.to_datetime(d["ex_date"].astype(str), format="%Y%m%d", errors="coerce")
    d = d.dropna(subset=["ex_date"])
    d["cash_div_tax"] = d["cash_div_tax"].astype(float).fillna(0.0)
    vals = []
    for t in dates:
        lo = t - pd.Timedelta(days=365)
        m = (d["ex_date"] <= t) & (d["ex_date"] > lo)
        vals.append(float(d.loc[m, "cash_div_tax"].sum()))
    return pd.Series(vals, index=dates)


def moneyflow_daily(mf: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    cols = ["mf_lg_net", "mf_sm_net", "mf_net"]
    if mf is None or mf.empty:
        return pd.DataFrame(np.nan, index=dates, columns=cols)
    m = mf.copy()
    m["trade_date"] = pd.to_datetime(m["trade_date"].astype(str), format="%Y%m%d")
    m = m.set_index("trade_date")
    out = pd.DataFrame(index=dates)
    out["mf_lg_net"] = (m["buy_lg_amount"] + m["buy_elg_amount"]
                        - m["sell_lg_amount"] - m["sell_elg_amount"]).reindex(dates)
    out["mf_sm_net"] = (m["buy_sm_amount"] - m["sell_sm_amount"]).reindex(dates)
    out["mf_net"] = m["net_mf_amount"].reindex(dates)
    return out


class PitFields:
    """按票读 tushare_extra.db 并产出 PIT 日频附加列。"""

    def __init__(self, db_path: str):
        self.con = sqlite3.connect(db_path)
        self.con.execute("PRAGMA query_only=1")
        self.missing = 0

    def _q(self, sql, code):
        try:
            return pd.read_sql_query(sql, self.con, params=(code,))
        except Exception:
            return pd.DataFrame()

    def for_code(self, code: str, dates: pd.DatetimeIndex) -> pd.DataFrame:
        inc = self._q("select ann_date,end_date,revenue,n_income_attr_p from ts_income where ts_code=?", code)
        cf = self._q("select ann_date,end_date,n_cashflow_act from ts_cashflow where ts_code=?", code)
        bs = self._q("select ann_date,end_date,total_assets from ts_balancesheet where ts_code=?", code)
        fi = self._q("select ann_date,end_date,q_roe,grossprofit_margin,q_sales_yoy,q_profit_yoy,debt_to_assets "
                     "from ts_fina_indicator where ts_code=?", code)
        div = self._q("select div_proc,ex_date,cash_div_tax from ts_dividend where ts_code=?", code)
        mf = self._q("select trade_date,buy_sm_amount,sell_sm_amount,buy_lg_amount,sell_lg_amount,"
                     "buy_elg_amount,sell_elg_amount,net_mf_amount from ts_moneyflow where ts_code=?", code)
        if inc.empty and fi.empty:
            self.missing += 1
        q = quarterly_derive(inc, cf, bs, fi)
        out = align_pit(q, dates)
        out["dps_ttm"] = dps_ttm(div, dates)
        out = out.join(moneyflow_daily(mf, dates))
        for c in PIT_COLS:
            if c not in out.columns:
                out[c] = np.nan
        return out[PIT_COLS].astype("float64")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_pit_fields.py -q`
Expected: 6 passed。若 `test_sue_*` 因数值细节失败,以测试意图为准修实现(SUE = yoy 差 / 历史 8 季 yoy 差 std,当期不入 std)。

- [ ] **Step 5: 真库冒烟**

```bash
.venv/bin/python - <<'EOF'
import pandas as pd
from app.quant.pit_fields import PitFields
p = PitFields("data/tushare_extra.db")
dates = pd.bdate_range("2024-01-01", "2026-09-15")
df = p.for_code("300750.SZ", dates)
print(df.tail(3).T)
print(df.loc["2025-03-14":"2025-03-18", ["np_ttm", "ann_age", "sue"]])   # 2025-03-15 年报公告(周六)→ 03-17 生效
EOF
```
Expected:`np_ttm` 在 2025-03-17 起变为 2024 全年值(≈5.07e10 附近),03-14 仍是旧值;`ann_age` 03-17=0。

- [ ] **Step 6: Commit**

```bash
git add app/quant/pit_fields.py tests/test_pit_fields.py
git commit -m "feat(research): PIT 财务/分红/资金流日频字段生成(pit_fields)"
```

---

### Task 3: 导出 merge 附加列

**Files:**
- Modify: `app/backtest/qlib_data.py:37-64`
- Test: `tests/test_backtest_qlib_data.py`

**Interfaces:**
- Produces: `export_market_csvs_full(session, codes, start, end, out_dir, extra_fn=None)`;`extra_fn(code, dates: DatetimeIndex) -> DataFrame(index=dates)`;附加列原样写入 CSV(dump_bin 自动成字段)。

- [ ] **Step 1: 写失败测试**

在 `tests/test_backtest_qlib_data.py` 末尾追加(查看文件顶部已有的 session/DailyQuote 夹具写法,复用同一 `_seed` 风格;若无,按下面自建):

```python
def test_export_full_merges_extra_columns(tmp_path):
    import pandas as pd
    from datetime import date
    from app.db.database import make_engine, make_session_factory, Base
    from app.db.models import DailyQuote
    from app.backtest.qlib_data import export_market_csvs_full
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = make_session_factory(eng)()
    for d, c in [(date(2025, 1, 2), 10.0), (date(2025, 1, 3), 11.0)]:
        s.add(DailyQuote(code="300750.SZ", trade_date=d, open=c, high=c, low=c, close=c,
                         vol=100.0, amount=1.0, adj_factor=1.0))
    s.commit()

    def extra(code, dates):
        assert code == "300750.SZ"
        return pd.DataFrame({"np_ttm": [1.0, 2.0], "mf_net": [None, 3.0]}, index=dates)

    n = export_market_csvs_full(s, ["300750.SZ"], date(2025, 1, 1), date(2025, 1, 31),
                                str(tmp_path), extra_fn=extra)
    assert n == 1
    df = pd.read_csv(tmp_path / "SZ300750.csv")
    assert list(df.columns)[:3] == ["date", "open", "high"]
    assert "np_ttm" in df.columns and "mf_net" in df.columns
    assert df["np_ttm"].tolist() == [1.0, 2.0]
    assert pd.isna(df["mf_net"].iloc[0]) and df["mf_net"].iloc[1] == 3.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_backtest_qlib_data.py::test_export_full_merges_extra_columns -q`
Expected: FAIL `TypeError: ... unexpected keyword argument 'extra_fn'`

- [ ] **Step 3: 实现**

`app/backtest/qlib_data.py` 的 `export_market_csvs_full` 改为:

```python
def export_market_csvs_full(session, codes, start, end, out_dir: str,
                            extra_fn=None) -> int:
    """全字段导出:直接查 DailyQuote(含换手/估值/市值/成交额,不复权),
    每只票一个 qlib 符号命名的 CSV。extra_fn(code, dates) 可返回 index=dates 的
    附加列(如 PIT 财务字段),按日期 merge 后一并写出。返回成功写出的只数。"""
    import pandas as pd
    from app.db.models import DailyQuote
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for code in codes:
        rows = session.scalars(
            select(DailyQuote).where(
                DailyQuote.code == code,
                DailyQuote.trade_date >= start,
                DailyQuote.trade_date <= end,
            ).order_by(DailyQuote.trade_date)).all()
        if not rows:
            continue
        df = pd.DataFrame([{
            "date": r.trade_date, "open": r.open, "high": r.high,
            "low": r.low, "close": r.close, "volume": r.vol,
            "factor": r.adj_factor, "turnover_rate": r.turnover_rate,
            "volume_ratio": r.volume_ratio, "circ_mv": r.circ_mv,
            "total_mv": r.total_mv, "pe": r.pe, "pb": r.pb,
            "amount": r.amount,
        } for r in rows], columns=_FULL_COLS)
        if extra_fn is not None:
            dates = pd.DatetimeIndex(pd.to_datetime(df["date"]))
            extra = extra_fn(code, dates)
            if extra is not None and len(extra):
                extra = extra.reset_index(drop=True)
                df = pd.concat([df, extra], axis=1)
        df.to_csv(out / f"{to_qlib_symbol(code)}.csv", index=False)
        n += 1
    return n
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_backtest_qlib_data.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backtest/qlib_data.py tests/test_backtest_qlib_data.py
git commit -m "feat(research): 导出 CSV 支持 extra_fn 附加 PIT 列"
```

---

### Task 4: 动态宇宙 `cyb_dyn`

**Files:**
- Modify: `app/quant/universe.py`
- Modify: `scripts/build_universe.py`
- Test: `tests/test_quant_universe.py`

**Interfaces:**
- Produces: `dynamic_rows(rows, *, cal_start: date, cal_end: date, min_list_days=120, prefixes=("300","301")) -> list[tuple[str, date, date]]`,`rows` 元素 `(code, name, list_date, delist_date|None)`;`write_instrument_rows(rows3, path) -> int`;`basic_from_extra_db(db_path) -> list[(code,name,list_date,delist_date)]`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_quant_universe.py` 末尾追加:

```python
from datetime import date
from app.quant.universe import dynamic_rows, write_instrument_rows


def test_dynamic_rows_start_end_and_filters():
    rows = [
        ("300001.SZ", "特锐德", date(2009, 10, 30), None),            # 老票:从 cal_start 起
        ("300999.SZ", "新票", date(2026, 6, 1), None),               # 次新:list+120 天 > cal_end → 剔除
        ("300500.SZ", "退市股", date(2015, 1, 1), date(2020, 6, 1)),  # 退市:end = delist−1
        ("300600.SZ", "*ST烂", date(2015, 1, 1), None),              # ST 剔除
        ("000001.SZ", "平安银行", date(1991, 4, 3), None),           # 非创业板
        ("300700.SZ", "刚满", date(2011, 1, 1), None),               # start = 2011-05-01
    ]
    out = dynamic_rows(rows, cal_start=date(2011, 1, 4), cal_end=date(2026, 9, 15))
    d = {c: (s, e) for c, s, e in out}
    assert d["300001.SZ"] == (date(2011, 1, 4), date(2026, 9, 15))
    assert "300999.SZ" not in d and "300600.SZ" not in d and "000001.SZ" not in d
    assert d["300500.SZ"] == (date(2015, 5, 1), date(2020, 5, 31))
    assert d["300700.SZ"] == (date(2011, 5, 1), date(2026, 9, 15))


def test_write_instrument_rows(tmp_path):
    p = tmp_path / "cyb_dyn.txt"
    n = write_instrument_rows([("300001.SZ", date(2011, 1, 4), date(2026, 9, 15))], p)
    assert n == 1
    assert p.read_text() == "SZ300001\t2011-01-04\t2026-09-15\n"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_universe.py -q`
Expected: FAIL `ImportError: cannot import name 'dynamic_rows'`

- [ ] **Step 3: 实现**

`app/quant/universe.py` 追加:

```python
from datetime import timedelta


def dynamic_rows(rows, *, cal_start: date, cal_end: date, min_list_days: int = 120,
                 prefixes: tuple = ("300", "301")) -> list[tuple[str, date, date]]:
    """按票给出动态起止日(供 qlib instruments 每行 SYMBOL START END):
    start = max(list_date + min_list_days, cal_start);end = delist_date−1 或 cal_end。
    只保留代码前缀在 prefixes 的票(空元组=不限);仍按当前名称剔 ST(已知局限)。
    start > end(次新或早退市)的票丢弃。rows 元素 (code, name, list_date, delist_date|None)。"""
    out = []
    for code, name, list_date, delist_date in rows:
        if prefixes and not code.split(".")[0].startswith(prefixes):
            continue
        if name and "ST" in name.upper():
            continue
        if list_date is None:
            continue
        start = max(list_date + timedelta(days=min_list_days), cal_start)
        end = min(delist_date - timedelta(days=1), cal_end) if delist_date else cal_end
        if start > end:
            continue
        out.append((code, start, end))
    return out


def write_instrument_rows(rows3, path) -> int:
    """写 qlib instruments:每行 `SYMBOL\\tSTART\\tEND`。返回行数。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{to_qlib_symbol(c)}\t{s.isoformat()}\t{e.isoformat()}" for c, s, e in rows3]
    p.write_text("\n".join(lines) + ("\n" if lines else ""))
    return len(lines)


def basic_from_extra_db(db_path: str) -> list[tuple]:
    """tushare_extra.db.ts_stock_basic → [(code, name, list_date, delist_date|None)],含已退市。"""
    import sqlite3
    from datetime import datetime
    con = sqlite3.connect(db_path)
    try:
        cur = con.execute("select ts_code,name,list_date,delist_date from ts_stock_basic")
        out = []
        for code, name, ld, dd in cur:
            f = lambda s: datetime.strptime(s, "%Y%m%d").date() if s else None
            out.append((code, name, f(ld), f(dd)))
        return out
    finally:
        con.close()
```

`scripts/build_universe.py` 的 `main()` 改为:

```python
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-list-days", type=int, default=120)
    p.add_argument("--name", default="investable")
    p.add_argument("--qlib-dir", default="", help="缺省 settings.qlib_data_dir;研究库传 data/qlib_cn_full")
    p.add_argument("--dynamic", action="store_true",
                   help="按票动态起止(上市满 N 天起、退市前一日止),含已退市股;基础信息读 tushare_extra.db")
    p.add_argument("--prefix", default="300,301", help="--dynamic 时的代码前缀过滤,空=全市场")
    p.add_argument("--extra-db", default="./data/tushare_extra.db")
    args = p.parse_args()

    s = get_settings()
    qlib_dir = Path(args.qlib_dir or s.qlib_data_dir)
    cal = qlib_dir / "calendars" / "day.txt"
    days = cal.read_text().split()
    start = datetime.strptime(days[0], "%Y-%m-%d").date()
    end = datetime.strptime(days[-1], "%Y-%m-%d").date()
    all_txt = (qlib_dir / "instruments" / "all.txt").read_text().splitlines()
    in_db = {from_qlib_symbol(ln.split("\t")[0]) for ln in all_txt if ln.strip()}
    path = qlib_dir / "instruments" / f"{args.name}.txt"

    if args.dynamic:
        from app.quant.universe import dynamic_rows, write_instrument_rows, basic_from_extra_db
        rows = basic_from_extra_db(args.extra_db)
        prefixes = tuple(x for x in args.prefix.split(",") if x)
        rows3 = [r for r in dynamic_rows(rows, cal_start=start, cal_end=end,
                                         min_list_days=args.min_list_days, prefixes=prefixes)
                 if r[0] in in_db]
        n = write_instrument_rows(rows3, path)
        print(f"UNIVERSE_DONE name={args.name} dynamic in={len(rows)} kept={n} -> {path}", flush=True)
        return

    rows = fetch_basic(s.tushare_token)
    investable = filter_investable(rows, as_of=end, min_list_days=args.min_list_days)
    codes = [c for c in investable if c in in_db]
    n = write_instruments(codes, str(path), start=start, end=end)
    print(f"UNIVERSE_DONE name={args.name} in={len(rows)} "
          f"investable={len(investable)} with_quotes={n} -> {path}", flush=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_quant_universe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/quant/universe.py scripts/build_universe.py tests/test_quant_universe.py
git commit -m "feat(research): 动态宇宙 dynamic_rows + build_universe --dynamic"
```

---

### Task 5: 多 regime 聚合模块 + 脚本

**Files:**
- Create: `app/quant/factor_regimes.py`
- Create: `scripts/run_factor_regimes.py`
- Test: `tests/test_factor_regimes.py`

**Interfaces:**
- Produces:
  - `REGIMES: list[tuple[str, str, str, str]]` = (key, label, start, end)。
  - `daily_rank_ic(score: pd.Series, label: pd.Series) -> pd.Series`(index=datetime)。
  - `aggregate(ric: pd.Series, regimes=REGIMES) -> dict`:`{"overall": {"ic","ir","days"}, "recent3y": {...}, "years": {yyyy: {...}}, "regimes": {key: {...}}}`。
  - `robust_all_regimes(agg: dict, *, min_same_sign=6, min_abs_ic=0.015, min_hits=5) -> bool`。
  - `render_md(report: dict) -> str`。

- [ ] **Step 1: 写失败测试**

`tests/test_factor_regimes.py`:

```python
import numpy as np
import pandas as pd
from app.quant.factor_regimes import (
    REGIMES, daily_rank_ic, aggregate, robust_all_regimes, render_md)


def _panel(days, n=30, corr_sign=1.0, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.MultiIndex.from_product([days, [f"S{i}" for i in range(n)]],
                                     names=["datetime", "instrument"])
    x = rng.normal(size=len(idx))
    y = corr_sign * x + 0.3 * rng.normal(size=len(idx))
    return pd.Series(x, index=idx), pd.Series(y, index=idx)


def test_regimes_cover_2011_to_now_contiguously():
    assert REGIMES[0][2] == "2011-01-01"
    for (_, _, _, e), (_, _, s, _) in zip(REGIMES, REGIMES[1:]):
        assert pd.Timestamp(e) + pd.Timedelta(days=1) == pd.Timestamp(s)
    assert REGIMES[-1][3] == "2099-12-31"


def test_daily_rank_ic_sign():
    days = pd.bdate_range("2025-01-01", periods=10)
    x, y = _panel(days, corr_sign=-1.0)
    ric = daily_rank_ic(x, y)
    assert len(ric) == 10 and (ric < 0).all()


def test_aggregate_buckets_years_and_regimes():
    days = pd.bdate_range("2014-06-20", "2015-07-10")
    x, y = _panel(days)
    ric = daily_rank_ic(x, y)
    agg = aggregate(ric)
    assert set(agg["years"]) == {"2014", "2015"}
    assert "R1" in agg["regimes"] and "R2" in agg["regimes"] and "R3" in agg["regimes"]
    assert agg["regimes"]["R2"]["days"] > agg["regimes"]["R3"]["days"]
    assert agg["overall"]["ic"] > 0.5 and agg["overall"]["ir"] > 0


def test_robust_all_regimes_rule():
    good = {"overall": {"ic": 0.03}, "regimes": {f"R{i}": {"ic": 0.02, "days": 50} for i in range(1, 8)}}
    assert robust_all_regimes(good)
    flip = {"overall": {"ic": 0.03}, "regimes": {**{f"R{i}": {"ic": 0.02, "days": 50} for i in range(1, 8)},
                                                 "R2": {"ic": -0.05, "days": 50}, "R5": {"ic": -0.01, "days": 50}}}
    assert not robust_all_regimes(flip)          # 只有 5 个同号 < 6
    weak = {"overall": {"ic": 0.03}, "regimes": {**{f"R{i}": {"ic": 0.02, "days": 50} for i in range(1, 8)},
                                                 **{f"R{i}": {"ic": 0.005, "days": 50} for i in range(1, 4)}}}
    assert not robust_all_regimes(weak)          # 达 0.015 的只有 4 个 < 5


def test_render_md_marks_directions():
    rep = {"as_of": "2026-09-16", "universe": "cyb_dyn", "horizon": 20, "start": "2011-01-04",
           "regimes": REGIMES,
           "factors": [{"name": "vol20", "family": "波动", "expr": "Std(...)", "in_frozen": True,
                        "robust_all": True, "agg": {"overall": {"ic": -0.05, "ir": -0.8, "days": 3000},
                                                    "recent3y": {"ic": -0.06, "ir": -0.9, "days": 700},
                                                    "years": {}, "regimes": {k: {"ic": -0.03, "ir": -0.5, "days": 100}
                                                                             for k, *_ in REGIMES}}}]}
    md = render_md(rep)
    assert "vol20" in md and "−" in md and "frozen" in md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_factor_regimes.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现 `app/quant/factor_regimes.py`**

```python
"""多 regime 因子稳健性:逐日 RankIC → 按年/按 regime 聚合 → 全周期稳健判定。"""
import numpy as np
import pandas as pd

# (key, 标签, 起, 止) —— 连续覆盖 2011 起
REGIMES = [
    ("R1", "2011-14上半 震荡熊", "2011-01-01", "2014-06-30"),
    ("R2", "2014下-15上 杠杆牛", "2014-07-01", "2015-06-30"),
    ("R3", "2015下-16初 股灾", "2015-07-01", "2016-02-29"),
    ("R4", "2016-18 白马/去杠杆", "2016-03-01", "2018-12-31"),
    ("R5", "2019-21 成长牛", "2019-01-01", "2021-12-31"),
    ("R6", "2022-24.8 小盘红利熊", "2022-01-01", "2024-08-31"),
    ("R7", "2024.9- 924后", "2024-09-01", "2099-12-31"),
]


def daily_rank_ic(score: pd.Series, label: pd.Series) -> pd.Series:
    """逐日截面 Spearman;两者 index 都是 (datetime, instrument)。"""
    j = pd.DataFrame({"s": score, "y": label}).dropna()
    out = {}
    for d, g in j.groupby(level="datetime"):
        if len(g) < 5 or g["s"].nunique() < 2 or g["y"].nunique() < 2:
            continue
        out[d] = g["s"].corr(g["y"], method="spearman")
    return pd.Series(out, dtype="float64").sort_index()


def _stats(s: pd.Series) -> dict:
    s = s.dropna()
    n = len(s)
    ic = float(s.mean()) if n else 0.0
    ir = float(s.mean() / s.std()) if n > 1 and s.std() else 0.0
    return {"ic": ic, "ir": ir, "days": int(n)}


def aggregate(ric: pd.Series, regimes=REGIMES) -> dict:
    idx = pd.DatetimeIndex(ric.index)
    out = {"overall": _stats(ric), "years": {}, "regimes": {}}
    last = idx.max() if len(idx) else pd.Timestamp("2000-01-01")
    out["recent3y"] = _stats(ric[idx >= last - pd.DateOffset(years=3)])
    for y, g in ric.groupby(idx.year):
        out["years"][str(y)] = _stats(g)
    for key, _label, s, e in regimes:
        m = (idx >= pd.Timestamp(s)) & (idx <= pd.Timestamp(e))
        if m.any():
            out["regimes"][key] = _stats(ric[m])
    return out


def robust_all_regimes(agg: dict, *, min_same_sign: int = 6,
                       min_abs_ic: float = 0.015, min_hits: int = 5) -> bool:
    """≥min_same_sign 个 regime 与全期同号,且 ≥min_hits 个 regime |ic|≥min_abs_ic。"""
    sign = np.sign(agg["overall"]["ic"]) or 1.0
    regs = [r for r in agg["regimes"].values() if r.get("days", 0) > 0]
    same = sum(1 for r in regs if np.sign(r["ic"]) == sign)
    hits = sum(1 for r in regs if abs(r["ic"]) >= min_abs_ic and np.sign(r["ic"]) == sign)
    return same >= min_same_sign and hits >= min_hits


def _mark(ic: float, thr: float = 0.015) -> str:
    return "+" if ic >= thr else ("−" if ic <= -thr else "0")


def render_md(rep: dict) -> str:
    keys = [k for k, *_ in rep["regimes"]]
    L = [f"# 因子多 regime 重检 {rep['as_of']}", "",
         f"- 宇宙 {rep['universe']} | h{rep['horizon']} | 起 {rep['start']} | 因子 {len(rep['factors'])}",
         "- regime:" + " / ".join(f"{k}={lbl}({s}~{e})" for k, lbl, s, e in rep["regimes"]),
         "- 方向标记:+ ≥+0.015,− ≤−0.015,0 介于其间;★=全周期稳健(≥6/7 同号且 ≥5 段 |IC|≥0.015)", ""]
    fams: dict = {}
    for f in rep["factors"]:
        fams.setdefault(f.get("family", "其他"), []).append(f)
    for fam, fs in fams.items():
        L.append(f"## {fam}")
        L.append("| 因子 | frozen | 全期IC/IR | 近3年IC | " + " | ".join(keys) + " | 稳健 |")
        L.append("|---|---|---|---|" + "---|" * len(keys) + "---|")
        for f in sorted(fs, key=lambda x: -abs(x["agg"]["overall"]["ir"])):
            a = f["agg"]
            marks = " | ".join(_mark(a["regimes"].get(k, {"ic": 0.0})["ic"]) if k in a["regimes"] else "·"
                               for k in keys)
            L.append(f"| {f['name']} | {'✓' if f.get('in_frozen') else ''} | "
                     f"{a['overall']['ic']:+.3f}/{a['overall']['ir']:+.2f} | {a['recent3y']['ic']:+.3f} | "
                     f"{marks} | {'★' if f.get('robust_all') else ''} |")
        L.append("")
    return "\n".join(L)
```

`scripts/run_factor_regimes.py`:

```python
"""多 regime 因子重检:在研究库(2010 起)上按年/按 regime 逐因子 RankIC。

用法:
  python scripts/run_factor_regimes.py                       # cyb_dyn, h=settings.discovery_horizon
  python scripts/run_factor_regimes.py --universe cyb_dyn --start 2011-01-04 --qlib-dir data/qlib_cn_full
产出:data/reports/factor_regimes_<asof>_h<h>.{json,md}
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings, resolve_horizon
from app.backtest.qlib_data import init_qlib
from app.quant.factor_mine import FACTOR_LIBRARY, label_expr, to_datetime_instrument
from app.quant.factor_regimes import (REGIMES, daily_rank_ic, aggregate,
                                      robust_all_regimes, render_md)


def _family(name: str) -> str:
    try:
        from app.quant.factor_mine import FACTOR_FAMILY
        return FACTOR_FAMILY.get(name, "其他")
    except ImportError:
        return "其他"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default="cyb_dyn")
    p.add_argument("--horizon", type=int, default=None)
    p.add_argument("--start", default="2011-01-04")
    p.add_argument("--qlib-dir", default="")
    p.add_argument("--limit", type=int, default=0, help="冒烟:只取前 N 只")
    args = p.parse_args()

    s = get_settings()
    horizon = resolve_horizon(args.horizon, s)
    qlib_dir = args.qlib_dir or s.qlib_research_dir
    init_qlib(qlib_dir)
    from qlib.data import D
    import pandas as pd

    end = D.calendar()[-1]
    insts = D.list_instruments(D.instruments(args.universe), as_list=True)
    if args.limit:
        insts = insts[: args.limit]
    # 研究库可用字段:跳过引用缺失字段的因子
    sample = D.features(insts[:1], ["$close"], start_time=args.start, end_time=end)
    avail = set(_available_fields(qlib_dir))
    names, skipped = [], []
    for n, expr in FACTOR_LIBRARY.items():
        need = set(re.findall(r"\$([a-z_]+)", expr))
        (names if need <= avail else skipped).append(n)
    try:
        from app.factors.frozen import load_frozen
        frozen = set(load_frozen(Path(s.qlib_data_dir).resolve().parent / "factors" / "frozen_composite.json").factors)
    except Exception:
        frozen = set()

    label = label_expr(horizon)
    print(f"regimes: {len(insts)} insts, {len(names)} factors (skip {skipped}), "
          f"{args.start}..{end.date()} h{horizon}", flush=True)
    df = D.features(insts, [FACTOR_LIBRARY[n] for n in names] + [label],
                    start_time=args.start, end_time=end)
    df.columns = names + ["label"]
    df = to_datetime_instrument(df).astype("float32")
    y = df["label"]
    factors = []
    for n in names:
        ric = daily_rank_ic(df[n], y)
        agg = aggregate(ric)
        rob = robust_all_regimes(agg)
        factors.append({"name": n, "family": _family(n), "expr": FACTOR_LIBRARY[n],
                        "in_frozen": n in frozen, "robust_all": rob, "agg": agg})
        marks = "".join("+" if agg["regimes"].get(k, {"ic": 0})["ic"] >= 0.015 else
                        ("−" if agg["regimes"].get(k, {"ic": 0})["ic"] <= -0.015 else "0")
                        for k, *_ in REGIMES)
        print(f"  {n:14s} all={agg['overall']['ic']:+.4f}/{agg['overall']['ir']:+.2f} "
              f"r3y={agg['recent3y']['ic']:+.4f} [{marks}] {'★' if rob else ''}"
              f"{' frozen' if n in frozen else ''}", flush=True)

    rep = {"as_of": end.date().isoformat(), "universe": args.universe, "horizon": horizon,
           "start": args.start, "regimes": REGIMES, "skipped": skipped,
           "n_robust_all": sum(f["robust_all"] for f in factors), "factors": factors}
    rep_dir = Path(qlib_dir).resolve().parent / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{end.date().isoformat()}_h{horizon}"
    (rep_dir / f"factor_regimes_{tag}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    (rep_dir / f"factor_regimes_{tag}.md").write_text(render_md(rep))
    print(f"ROBUST_ALL {rep['n_robust_all']}/{len(factors)}\nREPORT -> {rep_dir}/factor_regimes_{tag}.md\n"
          f"FACTOR_REGIMES_DONE", flush=True)


def _available_fields(qlib_dir: str) -> list[str]:
    feat = Path(qlib_dir) / "features"
    for d in feat.iterdir():
        if d.is_dir():
            return [f.name.split(".")[0] for f in d.iterdir() if f.name.endswith(".day.bin")]
    return []


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_factor_regimes.py -q`
Expected: 5 passed

- [ ] **Step 5: 用现有生产库冒烟脚本(不依赖研究库)**

Run: `.venv/bin/python scripts/run_factor_regimes.py --qlib-dir data/qlib_cn --universe cyb --start 2024-01-01 --limit 100`
Expected: 打印 48 行因子、`FACTOR_REGIMES_DONE`,报告写到 `data/reports/factor_regimes_<date>_h20.md`(冒烟结果随后会被全量覆盖)。

- [ ] **Step 6: Commit**

```bash
git add app/quant/factor_regimes.py scripts/run_factor_regimes.py tests/test_factor_regimes.py
git commit -m "feat(research): 多 regime 因子重检模块与脚本"
```

---

### Task 6: 构建研究库 + 动态宇宙 + 全量 regime 重检(检查点 1)

**Files:**(仅数据产物,不改代码)
- 产出 `data/qlib_cn_full/`、`data/qlib_cn_full/instruments/cyb_dyn.txt`、`data/reports/factor_regimes_<date>_h20.{json,md}`

- [ ] **Step 1: 导出研究库(后台,约 30~60 分钟)**

```bash
cd backend && nohup .venv/bin/python scripts/build_qlib_data.py --start 2010-01-01 \
  --csv-dir data/qlib_csv_full --qlib-dir data/qlib_cn_full --extra \
  > data/qlib_full_build.log 2>&1 &
```
等待 `QLIB_DUMP_DONE`。检查:`head -1 data/qlib_cn_full/calendars/day.txt` = 2010-01-04;`ls data/qlib_cn_full/features/sz300750 | wc -l` = 14 + 17 = 31 个 bin。

- [ ] **Step 2: 动态宇宙**

```bash
.venv/bin/python scripts/build_universe.py --dynamic --name cyb_dyn --qlib-dir data/qlib_cn_full
.venv/bin/python scripts/build_universe.py --dynamic --name investable_dyn --prefix "" --qlib-dir data/qlib_cn_full
```
Expected:cyb_dyn kept ≈ 1300~1450(含退市);投资域 ≈ 5500+。

- [ ] **Step 3: 全量 regime 重检**

```bash
nohup .venv/bin/python scripts/run_factor_regimes.py --universe cyb_dyn --start 2011-01-04 \
  > data/regimes_run.log 2>&1 &
```
(内存观察:`free -g`;若超 20 GB,改为按年分段 `D.features` 再拼接。)

- [ ] **Step 4: 检查点 1 —— 向用户汇报**

从 md 报告提炼:frozen 27 个里各有几个 ★、哪些因子在 R2/R5(牛市)翻号、哪些只在 R6/R7 有效;哪些非 frozen 因子反而全周期稳健。不用 markdown 表格发给用户(微信渠道),每条一行。

- [ ] **Step 5: Commit 报告(报告目录若在 gitignore 则跳过)**

```bash
git status --short data/reports | head
```

---

## Phase B — 新家族扩库 + 合成升级(检查点 2)

### Task 7: 因子库扩展 + 族映射

**Files:**
- Modify: `app/quant/factor_mine.py`
- Test: `tests/test_factor_mine.py`

**Interfaces:**
- Produces: `FUNDAMENTAL_FACTORS: dict`, `FLOW_FACTORS: dict`(均已合入 `FACTOR_LIBRARY`),`RESEARCH_ONLY: frozenset`(= FLOW 名),`FACTOR_FAMILY: dict[str,str]`,`required_fields(name) -> set[str]`。

- [ ] **Step 1: 改测试**

`tests/test_factor_mine.py` 全文替换为:

```python
import re
from app.quant.factor_mine import (
    FACTOR_LIBRARY, STYLE_FACTORS, FUNDAMENTAL_FACTORS, FLOW_FACTORS,
    RESEARCH_ONLY, FACTOR_FAMILY, required_fields)

_BASE_FIELDS = {"open", "high", "low", "close", "volume",
                "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
                "pe", "pb", "amount"}
_PIT_FIELDS = {"np_ttm", "rev_ttm", "ocf_ttm", "sue", "q_roe", "gm", "q_sales_yoy",
               "q_profit_yoy", "profit_acc", "accrual", "debt_to_assets", "total_assets",
               "ann_age", "dps_ttm", "mf_lg_net", "mf_sm_net", "mf_net"}


def test_style_factors_present_and_fields_valid():
    expected = {"ln_mv", "mv_chg20", "ep", "bp", "turn5", "turn20",
                "turn_chg5_20", "turn_std20", "amihud_amt20", "amt5_20",
                "vr5", "vr_chg"}
    assert expected == set(STYLE_FACTORS)
    for name in expected:
        assert required_fields(name) <= _BASE_FIELDS


def test_fundamental_and_flow_factors_reference_pit_fields_only():
    assert len(FUNDAMENTAL_FACTORS) == 16
    assert len(FLOW_FACTORS) == 5
    for name in list(FUNDAMENTAL_FACTORS) + list(FLOW_FACTORS):
        assert name in FACTOR_LIBRARY
        assert required_fields(name) <= _BASE_FIELDS | _PIT_FIELDS, name
        assert required_fields(name) & _PIT_FIELDS, f"{name} 应至少用一个 PIT 字段"
    assert RESEARCH_ONLY == frozenset(FLOW_FACTORS)


def test_every_factor_has_family():
    assert set(FACTOR_LIBRARY) == set(FACTOR_FAMILY)
    assert FACTOR_FAMILY["vol20"] == "波动" and FACTOR_FAMILY["ep_ttm"] == "估值"
    assert FACTOR_FAMILY["lg_net5"] == "资金流"


def test_library_total_count():
    assert len(FACTOR_LIBRARY) == 36 + 12 + 16 + 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_factor_mine.py -q`
Expected: FAIL `ImportError`

- [ ] **Step 3: 实现**

在 `app/quant/factor_mine.py` 的 `STYLE_FACTORS = frozenset({...})` 之后追加:

```python
# ★★★ 财务/分红家族(2026-09-16,依赖研究库 PIT 字段:pit_fields.PIT_COLS;
# 金额 元,$total_mv 万元,比率 %)
FUNDAMENTAL_FACTORS: dict[str, str] = {
    # 估值(TTM)
    "ep_ttm":  "$np_ttm/($total_mv*1e4+1)",
    "sp_ttm":  "$rev_ttm/($total_mv*1e4+1)",
    "cfp_ttm": "$ocf_ttm/($total_mv*1e4+1)",
    "dy":      "$dps_ttm/($close+1e-12)",
    # 质量
    "q_roe":   "$q_roe",
    "gm":      "$gm",
    "gm_chg":  "$gm-Ref($gm,250)",
    "accrual": "$accrual",
    "ocf_np":  "$ocf_ttm/(Abs($np_ttm)+1)",
    "lev":     "$debt_to_assets",
    # 成长
    "q_sales_yoy":  "$q_sales_yoy",
    "q_profit_yoy": "$q_profit_yoy",
    "profit_acc":   "$profit_acc",
    "sue":          "$sue",
    "asset_g":      "$total_assets/(Ref($total_assets,250)+1)-1",
    # 事件:公告后 20 个交易日内的 SUE(盈余公告后漂移)
    "pead":         "If(Le($ann_age,20),$sue,0)",
}

# 资金流家族:tushare 到期后无免费续接源 → 只做研究,不进 frozen
FLOW_FACTORS: dict[str, str] = {
    "lg_net5":    "Mean($mf_lg_net,5)/(Mean($amount,5)*0.1+1)",
    "lg_net20":   "Mean($mf_lg_net,20)/(Mean($amount,20)*0.1+1)",
    "sm_net5":    "Mean($mf_sm_net,5)/(Mean($amount,5)*0.1+1)",
    "lg_net_chg": "Mean($mf_lg_net,5)/(Mean($amount,5)*0.1+1)-Mean($mf_lg_net,20)/(Mean($amount,20)*0.1+1)",
    "mf_cons20":  "Mean(Greater($mf_lg_net,0)/(Abs($mf_lg_net)+1e-6),20)",
}
RESEARCH_ONLY = frozenset(FLOW_FACTORS)
FACTOR_LIBRARY.update(FUNDAMENTAL_FACTORS)
FACTOR_LIBRARY.update(FLOW_FACTORS)

# 因子族(合成时同族限量,防一族信息重复加权)
FACTOR_FAMILY: dict[str, str] = {
    **{n: "动量" for n in ("mom5", "mom10", "mom20", "mom60")},
    **{n: "反转" for n in ("rev1", "rev3", "rev5")},
    **{n: "波动" for n in ("vol10", "vol20", "vol60", "wvma20")},
    **{n: "风险调整动量" for n in ("sharpe20", "sharpe60")},
    **{n: "量能" for n in ("vmom", "turn_chg", "vstd20", "vr5", "vr_chg", "amt5_20")},
    **{n: "量价相关" for n in ("corr_pv10", "corr_pv20", "corr_rv10")},
    **{n: "价位" for n in ("pos20", "pos60", "ma_dist20", "ma_dist60")},
    **{n: "日内" for n in ("intra_ret", "intra_range", "intra_pos", "gap", "mean_intra20")},
    **{n: "趋势" for n in ("slope20", "rsqr20", "up_ratio14")},
    **{n: "流动性" for n in ("amihud20", "amihud_amt20")},
    **{n: "分布" for n in ("skew20", "kurt20")},
    **{n: "极值" for n in ("maxret20", "minret20")},
    **{n: "市值" for n in ("ln_mv", "mv_chg20")},
    **{n: "估值" for n in ("ep", "bp", "ep_ttm", "sp_ttm", "cfp_ttm")},
    **{n: "换手" for n in ("turn5", "turn20", "turn_chg5_20", "turn_std20")},
    **{n: "质量" for n in ("q_roe", "gm", "gm_chg", "accrual", "ocf_np", "lev")},
    **{n: "成长" for n in ("q_sales_yoy", "q_profit_yoy", "profit_acc", "sue", "asset_g", "pead")},
    "dy": "分红",
    **{n: "资金流" for n in FLOW_FACTORS},
}


def required_fields(name: str) -> set[str]:
    """因子表达式引用的 $字段 集合。"""
    import re
    return set(re.findall(r"\$([a-z_]+)", FACTOR_LIBRARY[name]))
```

同时把 `run_factor_mining.py` 顶部的 `NOVEL = NOVEL | STYLE_FACTORS` 改为
`NOVEL = NOVEL | STYLE_FACTORS | frozenset(FUNDAMENTAL_FACTORS) | frozenset(FLOW_FACTORS)`(import 同步补)。

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/test_factor_mine.py tests/test_discovery_runner.py tests/test_daily_full*.py -q`
Expected: PASS(生产 frozen 只引用旧因子,`qlib_provider` 不受影响)。

- [ ] **Step 5: Commit**

```bash
git add app/quant/factor_mine.py scripts/run_factor_mining.py tests/test_factor_mine.py
git commit -m "feat(factors): 财务/分红/资金流因子家族 + FACTOR_FAMILY 族映射"
```

---

### Task 8: 挖掘脚本支持研究库 + 长窗,跑全量

**Files:**
- Modify: `scripts/run_factor_mining.py`

**Interfaces:**
- Produces: `--qlib-dir`(缺省 settings.qlib_data_dir),`--is-start/--split` 长窗默认改为 `2011-01-04` / `2022-01-01`(仅当 `--qlib-dir` 指向研究库时,否则保持旧默认),缺字段因子进 `report["skipped"]`。

- [ ] **Step 1: 改脚本**

`build_parser()` 增:

```python
    p.add_argument("--qlib-dir", default="",
                   help="缺省 settings.qlib_data_dir;研究库传 data/qlib_cn_full(自动长窗 IS 2011~2021 / OOS 2022~)")
    p.add_argument("--long", action="store_true", help="强制长窗 IS 2011-01-04 / split 2022-01-01")
```

`main()` 中 `init_qlib(s.qlib_data_dir)` 改为:

```python
    qlib_dir = args.qlib_dir or s.qlib_data_dir
    init_qlib(qlib_dir)
    if args.long or (args.qlib_dir and "full" in args.qlib_dir):
        args.is_start, args.split = "2011-01-04", "2022-01-01"
```

因子列表构建改为(跳过缺字段):

```python
    from app.quant.factor_mine import required_fields
    avail = set(_available_fields(qlib_dir))
    names = [n for n in FACTOR_LIBRARY if required_fields(n) <= avail]
    skipped = [n for n in FACTOR_LIBRARY if n not in names]
    if skipped:
        print(f"skip (missing fields): {skipped}", flush=True)
```

并把 `_available_fields` 从 `run_factor_regimes.py` 复制到本脚本(或抽到 `app/backtest/qlib_data.py::available_fields(qlib_dir)` 并两处共用——推荐后者:在 `qlib_data.py` 追加:

```python
def available_fields(qlib_dir: str) -> list[str]:
    """研究/生产 qlib 库中任一票的字段名列表(features/<sym>/<field>.day.bin)。"""
    feat = Path(qlib_dir) / "features"
    for d in sorted(feat.iterdir()):
        if d.is_dir():
            return [f.name.split(".")[0] for f in d.iterdir() if f.name.endswith(".day.bin")]
    return []
```
并让 `run_factor_regimes.py` 也改用它。)

`report` 加 `"skipped": skipped, "qlib_dir": qlib_dir`;`rep_dir` 改为 `Path(qlib_dir).resolve().parent / "reports"`;`tag` 在研究库时追加 `_full`:

```python
    tag = ("smoke" if args.smoke else end.date().isoformat()) + f"_h{args.horizon}"
    if args.qlib_dir and "full" in args.qlib_dir:
        tag += "_full"
```

- [ ] **Step 2: 冒烟**

Run: `.venv/bin/python scripts/run_factor_mining.py --qlib-dir data/qlib_cn_full --universe cyb_dyn --smoke`
Expected: 69 因子(无 skip)、`FACTOR_MINING_DONE`。

- [ ] **Step 3: 全量长窗**

```bash
nohup .venv/bin/python scripts/run_factor_mining.py --qlib-dir data/qlib_cn_full --universe cyb_dyn \
  > data/mining_full.log 2>&1 &
```
产出 `data/reports/factor_mining_<date>_h20_full.{json,md}`。

- [ ] **Step 4: Commit**

```bash
git add scripts/run_factor_mining.py scripts/run_factor_regimes.py app/backtest/qlib_data.py
git commit -m "feat(research): 挖掘脚本支持研究库长窗与缺字段跳过"
```

---

### Task 9: 加权合成 + 族上限去重

**Files:**
- Modify: `app/quant/factor_compose.py`
- Modify: `app/factors/frozen.py`
- Modify: `app/discovery/qlib_provider.py:15-17`
- Test: `tests/test_quant_factor_compose.py`, `tests/test_frozen_select.py`

**Interfaces:**
- Produces:
  - `composite_score(panel, signs, weights=None)`。
  - `dedup_by_family(ranked, corr, family: dict, *, threshold=0.7, family_cap=2) -> list[str]`。
  - `ir_weights(kept: list[str], ir_map: dict[str,float], *, lo=0.5, hi=2.0) -> dict[str,float]`(|IR| 截断在 [lo×均值, hi×均值] 后归一,和为 1)。
  - `select_frozen(..., family=None, family_cap=2, ir_map=None)`:family 给了就用 `dedup_by_family`,ir_map 给了就用 `ir_weights`,否则维持旧行为。
  - `score_panel(panel, signs, weights=None)`;`run_qlib_discovery` 传 `frozen.weights`。

- [ ] **Step 1: 写失败测试**

`tests/test_quant_factor_compose.py` 末尾追加:

```python
from app.quant.factor_compose import dedup_by_family, ir_weights


def test_composite_score_weighted():
    idx = _idx(date(2026, 6, 1), ["A", "B", "C"])
    panel = pd.DataFrame({"f1": [1.0, 2.0, 3.0], "f2": [3.0, 2.0, 1.0]}, index=idx)
    eq = composite_score(panel, {"f1": 1.0, "f2": 1.0})
    assert abs(eq["score"]).max() < 1e-9                       # 等权互相抵消
    w = composite_score(panel, {"f1": 1.0, "f2": 1.0}, weights={"f1": 0.9, "f2": 0.1})
    assert w.loc[(pd.Timestamp(2026, 6, 1), "C"), "score"] > w.loc[(pd.Timestamp(2026, 6, 1), "A"), "score"]


def test_dedup_by_family_caps_per_family_and_corr():
    ranked = ["v1", "v2", "v3", "t1", "q1"]
    fam = {"v1": "波动", "v2": "波动", "v3": "波动", "t1": "换手", "q1": "质量"}
    import numpy as np
    corr = pd.DataFrame(np.eye(5), index=ranked, columns=ranked)
    corr.loc["t1", "v1"] = corr.loc["v1", "t1"] = 0.75          # t1 与 v1 高相关 → 丢
    kept = dedup_by_family(ranked, corr, fam, threshold=0.7, family_cap=2)
    assert kept == ["v1", "v2", "q1"]                           # v3 超族上限,t1 相关被丢


def test_ir_weights_clipped_and_normalized():
    w = ir_weights(["a", "b", "c"], {"a": -3.0, "b": 0.5, "c": 0.1})   # 均值 1.2 → 截断 [0.6, 2.4]
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert w["a"] == pytest.approx(2.4 / (2.4 + 0.6 + 0.6))
    assert w["b"] == w["c"]
```
(文件顶部补 `import pytest`。)

`tests/test_frozen_select.py` 末尾追加:

```python
def test_select_frozen_with_family_and_ir_weights():
    ranked = ["v1", "v2", "v3", "q1"]
    rank_ic = {"v1": -0.05, "v2": -0.04, "v3": -0.03, "q1": 0.02}
    corr = pd.DataFrame([[1, .2, .2, .1], [.2, 1, .2, .1], [.2, .2, 1, .1], [.1, .1, .1, 1]],
                        index=ranked, columns=ranked, dtype=float)
    ff = select_frozen(ranked, rank_ic, corr, universe="cyb", horizon=20,
                       source_report="r", as_of="2026-09-16", metrics={},
                       family={"v1": "波动", "v2": "波动", "v3": "波动", "q1": "质量"},
                       family_cap=2, ir_map={"v1": -1.0, "v2": -0.8, "q1": 0.4})
    assert ff.factors == ["v1", "v2", "q1"]
    assert abs(sum(ff.weights.values()) - 1.0) < 1e-9
    assert ff.weights["v1"] > ff.weights["q1"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_quant_factor_compose.py tests/test_frozen_select.py -q`
Expected: FAIL `ImportError` / `TypeError`

- [ ] **Step 3: 实现**

`app/quant/factor_compose.py`:

```python
def dedup_by_family(ranked: list[str], corr: pd.DataFrame, family: dict,
                    *, threshold: float = 0.7, family_cap: int = 2) -> list[str]:
    """按 ranked 顺序贪心:同族最多 family_cap 个,且与已留因子 |corr| 均 < threshold。"""
    kept: list[str] = []
    count: dict[str, int] = {}
    for f in ranked:
        fam = family.get(f, "其他")
        if count.get(fam, 0) >= family_cap:
            continue
        if all(abs(corr.loc[f, k]) < threshold for k in kept):
            kept.append(f)
            count[fam] = count.get(fam, 0) + 1
    return kept


def ir_weights(kept: list[str], ir_map: dict, *, lo: float = 0.5, hi: float = 2.0) -> dict:
    """|IR| 截断在 [lo×均值, hi×均值] 后归一;缺 IR 的按均值计。"""
    if not kept:
        return {}
    raw = {f: abs(ir_map.get(f) or 0.0) for f in kept}
    mean = sum(raw.values()) / len(raw) or 1.0
    clipped = {f: min(max(v if v > 0 else mean, lo * mean), hi * mean) for f, v in raw.items()}
    tot = sum(clipped.values())
    return {f: round(v / tot, 6) for f, v in clipped.items()}


def composite_score(panel: pd.DataFrame, signs: dict, weights: dict | None = None) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 的因子面板;signs: {因子:±1};
    weights: {因子:权重}(缺省等权;给了则按权重归一后加权)。
    返回单列 'score' 的 DataFrame(每日截面 z-score×符号后跨因子(加权)平均)。"""
    cols = [c for c in panel.columns if c in signs]
    if weights:
        w = {c: float(weights.get(c, 0.0)) for c in cols}
        tot = sum(w.values())
        if tot > 0:
            parts = [cs_zscore(panel[c]) * signs[c] * (w[c] / tot) for c in cols]
            return pd.DataFrame({"score": pd.concat(parts, axis=1).sum(axis=1)})
    parts = [cs_zscore(panel[c]) * signs[c] for c in cols]
    score = pd.concat(parts, axis=1).mean(axis=1)
    return pd.DataFrame({"score": score})
```

`app/factors/frozen.py` 的 `select_frozen`:

```python
def select_frozen(ranked, rank_ic, corr, *, universe, horizon, source_report, as_of,
                  metrics, threshold: float = 0.8, family: dict | None = None,
                  family_cap: int = 2, ir_map: dict | None = None) -> FrozenFactors:
    """按重要性降序的 ranked + 相关矩阵 corr 去重(family 给了则同族限量 family_cap),
    符号由 rank_ic 方向定;ir_map 给了则按 |IR| 截断加权,否则等权。"""
    if family:
        kept = dedup_by_family(ranked, corr, family, threshold=threshold, family_cap=family_cap)
    else:
        kept = dedup_by_correlation(ranked, corr, threshold=threshold)
    signs = {f: sign_correct(rank_ic[f]) for f in kept}
    if ir_map:
        weights = ir_weights(kept, ir_map)
    else:
        w = round(1.0 / len(kept), 6) if kept else 0.0
        weights = {f: w for f in kept}
    return FrozenFactors(as_of=as_of, factors=kept, signs=signs, weights=weights,
                         universe=universe, horizon=horizon,
                         source_report=source_report, metrics_at_freeze=metrics)
```
(import 行补 `dedup_by_family, ir_weights`。)

`app/discovery/qlib_provider.py`:

```python
def score_panel(panel: pd.DataFrame, signs: dict, weights: dict | None = None) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 因子面板 -> 单列 'score'。"""
    return composite_score(panel, signs, weights=weights)
```
`run_qlib_discovery` 里 `score_df = score_panel(panel, frozen.signs)` → `score_panel(panel, frozen.signs, frozen.weights)`。
`scripts/validate_frozen_alignment.py::alignment_report` 增 `weights=None` 参数并传给 `composite_score`;`main()` 传 `ff.weights`。

- [ ] **Step 4: 跑测试 + 全量回归**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 全绿(现有 27 等权 frozen 的 weights 之和为 1,加权结果与等权一致)。

- [ ] **Step 5: Commit**

```bash
git add app/quant/factor_compose.py app/factors/frozen.py app/discovery/qlib_provider.py scripts/validate_frozen_alignment.py tests/test_quant_factor_compose.py tests/test_frozen_select.py
git commit -m "feat(factors): 复合分数支持权重;冻结按族限量去重 + IR 加权"
```

---

### Task 10: 冻结候选 = regime 稳健 ∩ 长窗稳健;同窗对比;检查点 2

**Files:**
- Modify: `scripts/freeze_factors.py`
- Modify: `scripts/run_composite_backtest.py`

**Interfaces:**
- `freeze_factors.py --qlib-dir --report <mining_full.json> --regimes <regimes.json> --family-cap 2 --threshold 0.7 --out <path>`:`--regimes` 给了则候选 = mining robust ∩ regimes robust_all,且剔除 `RESEARCH_ONLY`;`--out` 给了写到该路径而非生产 frozen(默认仍写生产路径并归档旧的)。
- `run_composite_backtest.py --qlib-dir --frozen <frozen.json> --universe cyb_dyn --horizon 20 --bt-start 2022-01-01`:`--frozen` 给了直接用其 factors/signs/weights,不再从 mining 报告选。

- [ ] **Step 1: 改 `freeze_factors.py`**

`freeze()` 签名加 `qlib_dir=None, regimes_path=None, family_cap=2, out_path=None`,主体改为:

```python
    init_qlib(qlib_dir or settings.qlib_data_dir)
    ...
    robust = mining["robust_factors"]
    if regimes_path:
        reg = json.loads(Path(regimes_path).read_text())
        ok = {f["name"] for f in reg["factors"] if f["robust_all"]}
        robust = [r for r in robust if r["name"] in ok]
    from app.quant.factor_mine import RESEARCH_ONLY, FACTOR_FAMILY
    robust = [r for r in robust if r["name"] not in RESEARCH_ONLY]
    ranked = [r["name"] for r in robust]
    rank_ic = {r["name"]: r["rank_ic_oos"] for r in robust}
    ir_map = {r["name"]: r["rank_ic_ir_oos"] for r in robust}
    ...
    df = D.features(insts, fields, start_time=mining["oos_window"][0], end_time=end)
    ...
    ff = select_frozen(ranked, rank_ic, corr, universe=universe, horizon=horizon,
                       source_report=mining.get("as_of", "unknown"), as_of=str(end.date()),
                       metrics=mining.get("composite_metrics", {}), threshold=threshold,
                       family=FACTOR_FAMILY, family_cap=family_cap, ir_map=ir_map)
    save_frozen(ff, Path(out_path) if out_path else frozen_path(settings))
```
CLI 加 `--qlib-dir`、`--regimes`、`--family-cap`(默认 2)、`--threshold`(默认 0.7)、`--out`。

- [ ] **Step 2: 改 `run_composite_backtest.py`**

加 `--qlib-dir`、`--frozen`。`--frozen` 时:

```python
    if args.frozen:
        from app.factors.frozen import load_frozen
        ff = load_frozen(args.frozen)
        ranked_names, signs, kept, weights = list(ff.factors), dict(ff.signs), list(ff.factors), dict(ff.weights)
        mining = {"as_of": ff.source_report}
```
取数后跳过去重,`score = composite_score(panel[kept], {k: signs[k] for k in kept}, weights=weights)`;report 加 `"weights": weights, "frozen": args.frozen`;tag 加 `_` + frozen 文件名 stem。

- [ ] **Step 3: 产出候选 frozen(不覆盖生产)并同窗对比**

```bash
R=$(ls -t data/reports/factor_regimes_*_h20.json | head -1)
M=$(ls -t data/reports/factor_mining_*_h20_full.json | head -1)
.venv/bin/python scripts/freeze_factors.py --qlib-dir data/qlib_cn_full --universe cyb_dyn \
  --report "$M" --regimes "$R" --family-cap 2 --threshold 0.7 --out data/factors/candidate_composite.json
# 同窗对比(2022-01-01 起,含 R6/R7 两段)
.venv/bin/python scripts/run_composite_backtest.py --qlib-dir data/qlib_cn_full --universe cyb_dyn --horizon 20 \
  --bt-start 2022-01-01 --frozen data/factors/frozen_composite.json --no-save
.venv/bin/python scripts/run_composite_backtest.py --qlib-dir data/qlib_cn_full --universe cyb_dyn --horizon 20 \
  --bt-start 2022-01-01 --frozen data/factors/candidate_composite.json --no-save
```

- [ ] **Step 4: 验证闸(候选)**

`validate_frozen_alignment.py` 加 `--frozen` 与 `--qlib-dir`(默认生产),对候选跑:
`.venv/bin/python scripts/validate_frozen_alignment.py --frozen data/factors/candidate_composite.json --qlib-dir data/qlib_cn_full`
Expected: `ALIGNMENT PASS`。

- [ ] **Step 5: 检查点 2 —— 向用户汇报**

一行一条:候选因子列表与权重;旧 vs 新同窗年化/回撤/IR/换手;验证闸结果;若新组合含财务因子,说明需要先做 baostock 季度续接(spec"数据续接"节)才能进生产;建议替换与否。**不替换生产 frozen,等用户拍板。**

- [ ] **Step 6: Commit**

```bash
git add scripts/freeze_factors.py scripts/run_composite_backtest.py scripts/validate_frozen_alignment.py
git commit -m "feat(factors): 冻结支持 regime 交集/族上限/IR 权重;回测支持直接跑 frozen 文件"
```

---

## Self-Review

- **Spec 覆盖**:0.1(Task 1/3/6)、0.2(Task 2)、0.3(Task 4)、第 1 步(Task 5/6)、第 2 步(Task 7/8)、第 3 步(Task 9/10)、错误处理(Task 2 缺表 NaN、Task 5/8 缺字段跳过)、测试(各任务)。"数据续接"按 spec 明确延后到用户采用财务因子之后,不在本计划内。
- **占位符**:无 TBD;Task 5 Step 5 冒烟用生产库 `cyb`(有 48 因子全部字段)。
- **类型一致**:`extra_fn(code, dates)`(Task 1/2/3)、`PIT_COLS`(Task 2/7 字段集合一致:12 季频 + ann_age + dps_ttm + 3 资金流 = 17)、`available_fields`(Task 8 抽出后 Task 5 脚本改用)、`select_frozen(family, family_cap, ir_map)`(Task 9/10)、`composite_score(weights=)`(Task 9/10)。
