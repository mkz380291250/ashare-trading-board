# 风格因子挖掘(市值/估值/换手 + 20日标签)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 daily_quotes 里未用的 7 个字段(turnover_rate/volume_ratio/circ_mv/total_mv/pe/pb/amount)导入 qlib 数据,新增约 12 个风格因子,跑 h5+h20 两轮挖掘出对比报告——不动生产线。

**Architecture:** 路线A(spec 已批):CSV 导出层加字段 → vendored DumpDataAll 自动带上全部列 → FACTOR_LIBRARY 表达式直接引用 `$pe` 等 → 现有挖掘/去重/合成/回测全复用。

**Tech Stack:** SQLAlchemy 2.x、pandas、qlib(vendored dump_bin)、pytest。

## Global Constraints

- spec:`docs/superpowers/specs/2026-07-03-style-factor-mining-design.md`
- 不改 `data/factors/frozen_composite.json`、不动 22:00 生产链、不改辩论提示词
- 估值/换手/市值字段**不复权**;None → CSV 空值(qlib 读成 NaN)
- 不动 `DailyBar` dataclass(全站引用),新导出函数直接查 `DailyQuote`
- 长任务(重导/挖掘)必须 `nice -n 15` 后台跑(4核机,别抢网页 CPU)
- 后端测试命令:`cd backend && .venv/bin/python -m pytest <file> -q`
- 注意:`scripts/run_composite_backtest.py` 与 `app/backtest/strategy.py` 工作区已有未提交改动(用户的换手率优化),不要回退,提交时一并入库
- 提交尾行:`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: 全字段 CSV 导出函数 `export_market_csvs_full`

**Files:**
- Modify: `backend/app/backtest/qlib_data.py`(在 export_market_csvs 后加新函数)
- Modify: `backend/scripts/build_qlib_data.py`(切换到新函数)
- Test: `backend/tests/test_qlib_export_full.py`(新建)

**Interfaces:**
- Produces: `export_market_csvs_full(session, codes, start, end, out_dir: str) -> int`
  (返回成功写出的只数;CSV 列固定为 date,open,high,low,close,volume,factor,turnover_rate,volume_ratio,circ_mv,total_mv,pe,pb,amount;文件名 `{to_qlib_symbol(code)}.csv`)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_qlib_export_full.py
from datetime import date
from pathlib import Path
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
import app.db.models  # noqa
from app.db.models import DailyQuote
from app.backtest.qlib_data import export_market_csvs_full

EXPECTED_COLS = ["date", "open", "high", "low", "close", "volume", "factor",
                 "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
                 "pe", "pb", "amount"]


def _sess():
    e = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _quote(code, d, close, **kw):
    base = dict(code=code, trade_date=d, open=close, high=close, low=close,
                close=close, vol=1000.0, adj_factor=2.0, amount=5000.0,
                turnover_rate=1.5, volume_ratio=0.9, circ_mv=8.8e5,
                total_mv=9.9e5, pe=25.0, pb=3.0)
    base.update(kw)
    return DailyQuote(**base)


def test_exports_all_columns_unadjusted(tmp_path):
    s = _sess()
    s.add(_quote("600519.SH", date(2026, 6, 1), 100.0))
    s.commit()
    n = export_market_csvs_full(s, ["600519.SH"], date(2026, 6, 1),
                                date(2026, 6, 2), str(tmp_path))
    assert n == 1
    df = pd.read_csv(tmp_path / "SH600519.csv")
    assert list(df.columns) == EXPECTED_COLS
    assert df.loc[0, "factor"] == 2.0          # factor 单独一列
    assert df.loc[0, "turnover_rate"] == 1.5   # 原值,不复权
    assert df.loc[0, "pe"] == 25.0
    assert df.loc[0, "amount"] == 5000.0


def test_null_optionals_become_empty(tmp_path):
    s = _sess()
    s.add(_quote("000001.SZ", date(2026, 6, 1), 10.0,
                 pe=None, pb=None, turnover_rate=None, circ_mv=None,
                 total_mv=None, volume_ratio=None, amount=None))
    s.commit()
    export_market_csvs_full(s, ["000001.SZ"], date(2026, 6, 1),
                            date(2026, 6, 2), str(tmp_path))
    df = pd.read_csv(tmp_path / "SZ000001.csv")
    assert pd.isna(df.loc[0, "pe"]) and pd.isna(df.loc[0, "amount"])
    assert df.loc[0, "close"] == 10.0


def test_no_rows_skipped(tmp_path):
    s = _sess()
    n = export_market_csvs_full(s, ["600000.SH"], date(2026, 6, 1),
                                date(2026, 6, 2), str(tmp_path))
    assert n == 0
    assert not (tmp_path / "SH600000.csv").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_qlib_export_full.py -q`
Expected: FAIL `ImportError: cannot import name 'export_market_csvs_full'`

- [ ] **Step 3: 实现**

```python
# backend/app/backtest/qlib_data.py — 加在 export_market_csvs 之后
# 顶部补 import(文件已有 Path):
from sqlalchemy import select

_FULL_COLS = ["date", "open", "high", "low", "close", "volume", "factor",
              "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
              "pe", "pb", "amount"]


def export_market_csvs_full(session, codes, start, end, out_dir: str) -> int:
    """全字段导出:直接查 DailyQuote(含换手/估值/市值/成交额,不复权),
    每只票一个 qlib 符号命名的 CSV。返回成功写出的只数。"""
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
        df.to_csv(out / f"{to_qlib_symbol(code)}.csv", index=False)
        n += 1
    return n
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_qlib_export_full.py -q`
Expected: 3 passed

- [ ] **Step 5: build_qlib_data.py 切换到新函数**

```python
# backend/scripts/build_qlib_data.py 两处修改:
# import 行:
from app.backtest.qlib_data import (export_market_csvs_full, export_csi300_csv, build_bin)
# main() 里原 export_market_csvs(store, codes, start, end, args.csv_dir) 改为:
    n = export_market_csvs_full(session, codes, start, end, args.csv_dir)
# (store 变量与 QuoteStore import 若不再被引用则一并删除)
```

- [ ] **Step 6: 全量既有测试不回归**

Run: `cd backend && .venv/bin/python -m pytest tests/test_backtest_qlib_data.py tests/test_qlib_store.py -q`
Expected: 全 passed(旧 export_market_csvs 保留未删,旧测试不受影响)

- [ ] **Step 7: Commit**

```bash
git add backend/app/backtest/qlib_data.py backend/scripts/build_qlib_data.py backend/tests/test_qlib_export_full.py
git commit -m "feat: qlib导出加换手/估值/市值/成交额7字段(export_market_csvs_full)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: FACTOR_LIBRARY 新增 12 个风格因子

**Files:**
- Modify: `backend/app/quant/factor_mine.py`(FACTOR_LIBRARY 字典与 STYLE 集合)
- Modify: `backend/scripts/run_factor_mining.py`(NOVEL 标记沿用,STYLE 因子也标星)
- Test: `backend/tests/test_factor_mine.py`(追加)

**Interfaces:**
- Produces: `FACTOR_LIBRARY` 新键:ln_mv, mv_chg20, ep, bp, turn5, turn20,
  turn_chg5_20, turn_std20, amihud_amt20, amt5_20, vr5, vr_chg;
  `STYLE_FACTORS: frozenset[str]`(这 12 个名字)

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_factor_mine.py 追加
import re
from app.quant.factor_mine import FACTOR_LIBRARY, STYLE_FACTORS

_KNOWN_FIELDS = {"open", "high", "low", "close", "volume",
                 "turnover_rate", "volume_ratio", "circ_mv", "total_mv",
                 "pe", "pb", "amount"}


def test_style_factors_present_and_fields_valid():
    expected = {"ln_mv", "mv_chg20", "ep", "bp", "turn5", "turn20",
                "turn_chg5_20", "turn_std20", "amihud_amt20", "amt5_20",
                "vr5", "vr_chg"}
    assert expected == set(STYLE_FACTORS)
    assert expected <= set(FACTOR_LIBRARY)
    for name in expected:
        fields = set(re.findall(r"\$([a-z_]+)", FACTOR_LIBRARY[name]))
        assert fields <= _KNOWN_FIELDS, f"{name} 引用未知字段 {fields}"


def test_library_total_count():
    assert len(FACTOR_LIBRARY) == 34 + 12
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_factor_mine.py -q`
Expected: FAIL `ImportError: cannot import name 'STYLE_FACTORS'`

- [ ] **Step 3: 实现——FACTOR_LIBRARY 追加(字典末尾)**

```python
# backend/app/quant/factor_mine.py — FACTOR_LIBRARY 末尾追加:
    # ★★ 风格因子(2026-07-03,依赖全字段 qlib 数据:turnover_rate/pe/pb/circ_mv/amount/volume_ratio)
    # 市值
    "ln_mv": "Log($circ_mv+1)",
    "mv_chg20": "$circ_mv/(Ref($circ_mv,20)+1e-12)-1",
    # 估值(EP=1/PE:PE负→EP负天然有序;null→NaN 由 dropna 跳过)
    "ep": "1/($pe+1e-12)",
    "bp": "1/($pb+1e-12)",
    # 换手
    "turn5": "Mean($turnover_rate,5)",
    "turn20": "Mean($turnover_rate,20)",
    "turn_chg5_20": "Mean($turnover_rate,5)/(Mean($turnover_rate,20)+1e-12)",
    "turn_std20": "Std($turnover_rate,20)/(Mean($turnover_rate,20)+1e-12)",
    # 流动性(真实成交额版 Amihud)
    "amihud_amt20": "Mean(Abs($close/Ref($close,1)-1)/($amount+1),20)",
    "amt5_20": "Mean($amount,5)/(Mean($amount,20)+1)",
    # 量比
    "vr5": "Mean($volume_ratio,5)",
    "vr_chg": "$volume_ratio/(Mean($volume_ratio,20)+1e-12)",
}

STYLE_FACTORS = frozenset({
    "ln_mv", "mv_chg20", "ep", "bp", "turn5", "turn20", "turn_chg5_20",
    "turn_std20", "amihud_amt20", "amt5_20", "vr5", "vr_chg"})
```

- [ ] **Step 4: run_factor_mining.py 星标风格因子**

```python
# backend/scripts/run_factor_mining.py:
# import 行改:
from app.quant.factor_mine import (
    FACTOR_LIBRARY, STYLE_FACTORS, label_expr, to_datetime_instrument,
    rank_by_abs_ir, is_robust)
# NOVEL 定义行下面加:
NOVEL = NOVEL | STYLE_FACTORS   # 风格因子也按"新"标星展示
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_factor_mine.py -q`
Expected: 全 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/quant/factor_mine.py backend/scripts/run_factor_mining.py backend/tests/test_factor_mine.py
git commit -m "feat: 新增12个风格因子(市值/估值/换手/流动性/量比)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 挖掘报告文件名带 horizon 后缀

**Files:**
- Modify: `backend/scripts/run_factor_mining.py`(tag 命名)

**Interfaces:**
- Produces: 报告文件 `factor_mining_<asof>_h<horizon>.{json,md}`(smoke 为
  `factor_mining_smoke_h<horizon>.*`);json 内容结构不变

- [ ] **Step 1: 修改 tag 行**

```python
# backend/scripts/run_factor_mining.py 原:
    tag = "smoke" if args.smoke else end.date().isoformat()
# 改为:
    tag = ("smoke" if args.smoke else end.date().isoformat()) + f"_h{args.horizon}"
```

- [ ] **Step 2: 确认 run_composite_backtest 的 glob 兼容**

`_latest_mining_report` 用 `glob("factor_mining_*.json")` 排序取最后+过滤 smoke——
新文件名 `..._h5.json`/`..._h20.json` 均匹配,但"取最后"会歧义(h20 排在 h5 后)。
Task 4 给它加 `--report` 显式指定,此处不改。

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/run_factor_mining.py
git commit -m "feat: 挖掘报告文件名带horizon后缀,h5/h20两轮互不覆盖

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: run_composite_backtest 支持 --report 显式指定挖掘报告

**Files:**
- Modify: `backend/scripts/run_composite_backtest.py`
  (注意:该文件工作区已有未提交的换手率优化改动,叠加修改、一并提交)

**Interfaces:**
- Produces: `--report <path>` 参数;缺省行为不变(取目录最新非 smoke)

- [ ] **Step 1: 加参数与分支**

```python
# backend/scripts/run_composite_backtest.py main() 的 argparse 段加:
    p.add_argument("--report", default="",
                   help="显式指定 factor_mining_*.json 路径;缺省取目录最新")
# 原 mining = _latest_mining_report(reports_dir) 改为:
    if args.report:
        mining = json.loads(Path(args.report).read_text())
    else:
        mining = _latest_mining_report(reports_dir)
```

- [ ] **Step 2: 冒烟验证参数解析**

Run: `cd backend && .venv/bin/python -c "import scripts.run_composite_backtest" 2>/dev/null || .venv/bin/python scripts/run_composite_backtest.py --help | grep report`
Expected: 帮助文本里出现 `--report`

- [ ] **Step 3: Commit(连同工作区已有的换手率优化一起入库)**

```bash
git add backend/scripts/run_composite_backtest.py backend/app/backtest/strategy.py
git commit -m "feat: 复合回测支持--report指定挖掘报告;入库换手率优化(周频信号/持有集/交易统计)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: 冒烟全链验证(小池)

**Files:** 无代码改动,纯运行验证。

- [ ] **Step 1: 小池重导(300只)**

```bash
cd backend && rm -rf data/qlib_csv_smoke && nice -n 15 .venv/bin/python scripts/build_qlib_data.py --csv-dir ./data/qlib_csv_smoke --qlib-dir ./data/qlib_cn_smoke --limit 300
```
Expected: `QLIB_DUMP_DONE`;`head -1 data/qlib_csv_smoke/SH600000.csv`(或任一文件)列含 turnover_rate,pe,pb,amount

- [ ] **Step 2: 冒烟挖掘(用 smoke 库跑通新因子表达式)**

```bash
cd backend && QLIB_DATA_DIR=./data/qlib_cn_smoke nice -n 15 .venv/bin/python scripts/run_factor_mining.py --smoke
```
注:Settings 是 pydantic BaseSettings,环境变量 `QLIB_DATA_DIR` 直接覆盖
`s.qlib_data_dir`,冒烟挖掘跑在小库上,新字段有真值,表达式端到端可验证。
Expected: `FACTOR_MINING_DONE`,46 个因子全部出数(样本小 IC 数值无意义,不报错即可)

- [ ] **Step 3: 检查报告文件名**

```bash
ls backend/data/reports/factor_mining_smoke_h5.*
```
Expected: json+md 两个文件存在

- [ ] **Step 4: 清理 smoke 产物,Commit(若有为通过冒烟而做的修正)**

```bash
rm -rf backend/data/qlib_csv_smoke backend/data/qlib_cn_smoke
git add -A backend/app backend/scripts && git status --short
# 若有修正则提交,无则跳过
```

---

### Task 6: 全量重导 + 两轮挖掘(后台长任务)

**Files:** 无代码改动。产出 4 份报告文件。

- [ ] **Step 1: 全量重导 qlib 数据(后台,~30-60分钟)**

```bash
cd backend && nice -n 15 .venv/bin/python scripts/build_qlib_data.py > /tmp/qlib_redump.log 2>&1
```
Expected: 日志尾部 `QLIB_DUMP_DONE`;抽查 `data/qlib_csv/SH600519.csv` 含新列且近期日期 pe/turnover_rate 有值

- [ ] **Step 2: h5 挖掘(后台)**

```bash
cd backend && nice -n 15 .venv/bin/python scripts/run_factor_mining.py --horizon 5 > /tmp/mining_h5.log 2>&1
```
Expected: `FACTOR_MINING_DONE`;`data/reports/factor_mining_<asof>_h5.{json,md}`

- [ ] **Step 3: h20 挖掘(后台)**

```bash
cd backend && nice -n 15 .venv/bin/python scripts/run_factor_mining.py --horizon 20 > /tmp/mining_h20.log 2>&1
```
Expected: `factor_mining_<asof>_h20.{json,md}`;重点看 mom/slope/sharpe 系 OOS RankIC 符号

- [ ] **Step 4: h5 新因子集复合回测(后台)**

```bash
cd backend && nice -n 15 .venv/bin/python scripts/run_composite_backtest.py --report data/reports/factor_mining_<asof>_h5.json > /tmp/composite_new.log 2>&1
```
Expected: `composite_backtest_<asof>.{json,md}` 产出

---

### Task 7: 新旧对比汇总,交付用户

**Files:**
- Create: `backend/data/reports/style_mining_summary_<asof>.md`(手写汇总)

- [ ] **Step 1: 汇总四份产出写对比文档**

内容(从 h5/h20 报告与新旧 composite 回测 json 提取,不新写代码):
- 12 个风格因子 h5 的 IS/OOS RankIC、IR、是否过稳健门槛,与量价因子 Top5 并排
- h20 下动量/趋势系因子符号是否翻正(逐个列 mom5/10/20/60、slope20、sharpe20/60、ma_dist)
- 新旧复合因子回测对比:RankIC/IR/年化/回撤/换手(旧=2026-06-17 报告)
- 结论建议(换不换 frozen、要不要走 h20 长周期线)

- [ ] **Step 2: 全量测试回归**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: 342+新增 全 passed

- [ ] **Step 3: Commit + 用户交付**

```bash
git add backend/data/reports/
git commit -m "docs: 风格因子挖掘h5/h20报告与新旧对比汇总

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
微信按短消息纪律发对比结论(不发表格,纯文字要点),等用户拍板是否重冻结。
