# Phase 1: qlib 复合因子接线 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让线上选股用经过优化的 qlib 复合因子(RankIC 0.069)完全替掉 MomentumProvider:冻结因子集为产物,每日对全市场打分取排序写入 DiscoveryPick。

**Architecture:** 纯逻辑(冻结产物 I/O、因子选择、复合打分、取最新截面)做成不依赖 qlib 的可单测函数;qlib 取数做成薄包装,只在集成测试里跑真实数据。选股入口 `run_discovery.py` 增加 `--source qlib`(默认),qlib 路径直接产出排序写 DiscoveryPick,不经 DiscoveryScorer 的百分位机制。

**Tech Stack:** Python 3.11, pandas, qlib, SQLAlchemy, pytest。复用 `app/quant/factor_compose.py`(`composite_score`/`dedup_by_correlation`/`sign_correct`)、`app/quant/ml_pipeline.py`(`cs_zscore`)、`app/quant/factor_mine.py`(`FACTOR_LIBRARY`)。

## Global Constraints

- Python 3.11;依赖不新增第三方库,只用项目已装的 pandas/qlib/sqlalchemy/pytest
- 因子表达式只从 `app/quant/factor_mine.py` 的 `FACTOR_LIBRARY` 取,冻结产物**只存因子名不存表达式**
- 复合分约定沿用 `composite_score`:每因子按日截面 z-score × 符号后跨因子等权;符号由 `sign_correct(rank_ic)` 定(rank_ic<0 取 -1,否则 +1)
- DiscoveryPick 落库字段固定:`as_of: date, code: str, rank: int(从1起), score: float, factors: str(JSON)`
- qlib 数据目录由 `get_settings().qlib_data_dir` 提供(默认 `./data/qlib_cn`),用前需 `init_qlib(qlib_dir)`
- 冻结产物路径:`<qlib_data_dir 的父目录>/factors/frozen_composite.json`,旧版归档到同目录 `archive/frozen_composite_<as_of>.json`
- 测试分两类:纯逻辑用单元测试(不碰 qlib);碰 qlib 的标 `@pytest.mark.integration`,需真实 `data/qlib_cn`

---

### Task 1: 冻结产物数据结构与读写

**Files:**
- Create: `backend/app/factors/__init__.py`
- Create: `backend/app/factors/frozen.py`
- Test: `backend/tests/test_frozen_factors.py`

**Interfaces:**
- Produces:
  - `@dataclass FrozenFactors` 字段:`as_of: str, factors: list[str], signs: dict[str, float], weights: dict[str, float], universe: str, horizon: int, source_report: str, metrics_at_freeze: dict`
  - `load_frozen(path: str | Path) -> FrozenFactors` — 文件不存在抛 `FileNotFoundError`
  - `save_frozen(ff: FrozenFactors, path: str | Path) -> None` — 若目标已存在,先把旧文件复制到同目录 `archive/frozen_composite_<旧as_of>.json` 再覆盖

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_frozen_factors.py
import json
import pytest
from app.factors.frozen import FrozenFactors, load_frozen, save_frozen


def _sample() -> FrozenFactors:
    return FrozenFactors(
        as_of="2026-06-25",
        factors=["vstd20", "rev3"],
        signs={"vstd20": -1.0, "rev3": 1.0},
        weights={"vstd20": 0.5, "rev3": 0.5},
        universe="investable",
        horizon=5,
        source_report="factor_mining_2026-06-25",
        metrics_at_freeze={"rank_ic_mean": 0.0695, "rank_ic_ir": 0.58},
    )


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "frozen_composite.json"
    save_frozen(_sample(), p)
    ff = load_frozen(p)
    assert ff.factors == ["vstd20", "rev3"]
    assert ff.signs["vstd20"] == -1.0
    assert ff.horizon == 5
    assert ff.metrics_at_freeze["rank_ic_ir"] == 0.58


def test_load_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_frozen(tmp_path / "nope.json")


def test_save_archives_previous(tmp_path):
    p = tmp_path / "frozen_composite.json"
    save_frozen(_sample(), p)
    newer = _sample()
    newer.as_of = "2026-07-01"
    save_frozen(newer, p)
    archived = tmp_path / "archive" / "frozen_composite_2026-06-25.json"
    assert archived.exists()
    assert json.loads(archived.read_text())["as_of"] == "2026-06-25"
    assert load_frozen(p).as_of == "2026-07-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_frozen_factors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.factors'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/factors/__init__.py
```

```python
# backend/app/factors/frozen.py
"""冻结复合因子产物的读写。只存因子名(表达式从 FACTOR_LIBRARY 取),
权重现为等权,保留字段以备扩展。覆盖写时把旧产物归档到 archive/ 供回滚。"""
import json
import shutil
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class FrozenFactors:
    as_of: str
    factors: list[str]
    signs: dict[str, float]
    weights: dict[str, float]
    universe: str
    horizon: int
    source_report: str
    metrics_at_freeze: dict = field(default_factory=dict)


def load_frozen(path: str | Path) -> FrozenFactors:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"frozen factors not found at {p}")
    return FrozenFactors(**json.loads(p.read_text()))


def save_frozen(ff: FrozenFactors, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = json.loads(p.read_text())
        archive = p.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, archive / f"frozen_composite_{old.get('as_of', 'unknown')}.json")
    p.write_text(json.dumps(asdict(ff), ensure_ascii=False, indent=2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_frozen_factors.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/factors/__init__.py backend/app/factors/frozen.py backend/tests/test_frozen_factors.py
git commit -m "feat(factors): frozen composite factor artifact I/O"
```

---

### Task 2: 从挖掘报告选定冻结因子集(纯逻辑)

**Files:**
- Modify: `backend/app/factors/frozen.py`
- Test: `backend/tests/test_frozen_select.py`

**Interfaces:**
- Consumes: Task 1 的 `FrozenFactors`;`app.quant.factor_compose.dedup_by_correlation`、`sign_correct`
- Produces:
  - `select_frozen(ranked: list[str], rank_ic: dict[str, float], corr: pd.DataFrame, *, universe: str, horizon: int, source_report: str, as_of: str, metrics: dict, threshold: float = 0.8) -> FrozenFactors`
  - 内部:按 `ranked` 顺序用 `dedup_by_correlation` 去重得 `kept`;`signs = {f: sign_correct(rank_ic[f]) for f in kept}`;`weights` 对 `kept` 等权

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_frozen_select.py
import pandas as pd
from app.factors.frozen import select_frozen


def test_select_dedup_and_signs():
    ranked = ["a", "b", "c"]          # 已按 |IR| 降序
    rank_ic = {"a": -0.05, "b": 0.04, "c": -0.03}
    # a 与 c 高度相关(0.9),应丢掉排名靠后的 c;b 独立
    corr = pd.DataFrame(
        [[1.0, 0.1, 0.9], [0.1, 1.0, 0.1], [0.9, 0.1, 1.0]],
        index=ranked, columns=ranked)
    ff = select_frozen(ranked, rank_ic, corr, universe="investable", horizon=5,
                       source_report="factor_mining_2026-06-25", as_of="2026-06-25",
                       metrics={"rank_ic_mean": 0.07}, threshold=0.8)
    assert ff.factors == ["a", "b"]            # c 被相关去重
    assert ff.signs == {"a": -1.0, "b": 1.0}   # a 反向、b 正向
    assert ff.weights == {"a": 0.5, "b": 0.5}  # 等权
    assert ff.horizon == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_frozen_select.py -v`
Expected: FAIL with `ImportError: cannot import name 'select_frozen'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/factors/frozen.py`:

```python
import pandas as pd
from app.quant.factor_compose import dedup_by_correlation, sign_correct


def select_frozen(ranked: list[str], rank_ic: dict[str, float], corr: pd.DataFrame,
                  *, universe: str, horizon: int, source_report: str, as_of: str,
                  metrics: dict, threshold: float = 0.8) -> FrozenFactors:
    """按重要性降序的 ranked + 相关矩阵 corr 去重,符号由 rank_ic 方向定,等权。"""
    kept = dedup_by_correlation(ranked, corr, threshold=threshold)
    signs = {f: sign_correct(rank_ic.get(f)) for f in kept}
    w = round(1.0 / len(kept), 6) if kept else 0.0
    weights = {f: w for f in kept}
    return FrozenFactors(as_of=as_of, factors=kept, signs=signs, weights=weights,
                         universe=universe, horizon=horizon,
                         source_report=source_report, metrics_at_freeze=metrics)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_frozen_select.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/factors/frozen.py backend/tests/test_frozen_select.py
git commit -m "feat(factors): select frozen factor set from mining report (dedup+signs+equal weight)"
```

---

### Task 3: 复合打分取最新截面(纯逻辑)

**Files:**
- Create: `backend/app/discovery/qlib_provider.py`
- Test: `backend/tests/test_qlib_compose_score.py`

**Interfaces:**
- Consumes: `app.quant.factor_compose.composite_score`
- Produces:
  - `score_panel(panel: pd.DataFrame, signs: dict) -> pd.DataFrame` — 直接转调 `composite_score`,返回单列 `score` 的 DataFrame(MultiIndex datetime,instrument)
  - `latest_section(score_df: pd.DataFrame) -> pd.Series` — 取最大 datetime 那一截面,index=instrument,降序排列

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_qlib_compose_score.py
import pandas as pd
from app.discovery.qlib_provider import score_panel, latest_section


def _panel():
    # 两天 × 三股,两个因子;MultiIndex(datetime, instrument)
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-06-24", "2026-06-25"]), ["A", "B", "C"]],
        names=["datetime", "instrument"])
    return pd.DataFrame({"f1": [1.0, 2.0, 3.0, 3.0, 2.0, 1.0],
                         "f2": [3.0, 2.0, 1.0, 1.0, 2.0, 3.0]}, index=idx)


def test_score_panel_returns_score_column():
    s = score_panel(_panel(), {"f1": 1.0, "f2": 1.0})
    assert list(s.columns) == ["score"]
    assert len(s) == 6


def test_latest_section_picks_last_day_sorted_desc():
    s = score_panel(_panel(), {"f1": 1.0, "f2": -1.0})  # f1 越大越好,f2 反向
    sec = latest_section(s)
    # 2026-06-25 截面:A f1=3,f2=1 -> 最高;C f1=1,f2=3 -> 最低
    assert sec.index[0] == "A"
    assert sec.index[-1] == "C"
    assert sec.is_monotonic_decreasing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_qlib_compose_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.discovery.qlib_provider'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/discovery/qlib_provider.py
"""qlib 复合因子选股:加载冻结产物,对全市场打分取最新交易日截面排序。
纯逻辑(score_panel/latest_section)不依赖 qlib;qlib 取数在 score_universe 里。"""
import pandas as pd
from app.quant.factor_compose import composite_score


def score_panel(panel: pd.DataFrame, signs: dict) -> pd.DataFrame:
    """panel: MultiIndex(datetime,instrument) 因子面板 -> 单列 'score'。"""
    return composite_score(panel, signs)


def latest_section(score_df: pd.DataFrame) -> pd.Series:
    """取最新 datetime 截面,返回 index=instrument 的降序 Series。"""
    last = score_df.index.get_level_values("datetime").max()
    sec = score_df.xs(last, level="datetime")["score"]
    return sec.sort_values(ascending=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_qlib_compose_score.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/discovery/qlib_provider.py backend/tests/test_qlib_compose_score.py
git commit -m "feat(discovery): composite score panel + latest cross-section helpers"
```

---

### Task 4: qlib 取数打分 + 写 DiscoveryPick

**Files:**
- Modify: `backend/app/discovery/qlib_provider.py`
- Test: `backend/tests/test_qlib_discovery_run.py`

**Interfaces:**
- Consumes: Task 1 `load_frozen`、Task 3 `score_panel`/`latest_section`;`FACTOR_LIBRARY`、`to_datetime_instrument`、`DiscoveryPick`
- Produces:
  - `load_features(insts: list[str], factors: list[str], as_of: date, lookback: int) -> pd.DataFrame` — qlib `D.features` 薄包装,按 `as_of` 回溯 `lookback` 交易日取数,返回列名=因子名、MultiIndex(datetime,instrument) 的面板(集成测试覆盖)
  - `run_qlib_discovery(session, as_of: date, frozen: FrozenFactors, insts: list[str], *, lookback: int = 60, load_features_fn=load_features) -> list[tuple[str, float]]` — 打分取最新截面,**全量**覆盖写 `DiscoveryPick`(rank 从 1 起),返回 [(code, score)] 降序。`load_features_fn` 可注入以便单测

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_qlib_discovery_run.py
import json
from datetime import date
import pandas as pd
from sqlalchemy import select
from app.db.database import make_engine, make_session_factory, Base
import app.db.models  # noqa: F401
from app.db.models import DiscoveryPick
from app.factors.frozen import FrozenFactors
from app.discovery.qlib_provider import run_qlib_discovery


def _session():
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    return make_session_factory(eng)()


def _fake_features(insts, factors, as_of, lookback):
    idx = pd.MultiIndex.from_product(
        [pd.to_datetime(["2026-06-24", "2026-06-25"]), insts],
        names=["datetime", "instrument"])
    data = {f: list(range(len(idx))) for f in factors}
    return pd.DataFrame(data, index=idx)


def test_run_qlib_discovery_writes_full_ranking():
    s = _session()
    frozen = FrozenFactors(as_of="2026-06-25", factors=["f1"], signs={"f1": 1.0},
                           weights={"f1": 1.0}, universe="investable", horizon=5,
                           source_report="r", metrics_at_freeze={})
    out = run_qlib_discovery(s, date(2026, 6, 25), frozen, ["A", "B", "C"],
                             load_features_fn=_fake_features)
    rows = s.execute(select(DiscoveryPick).order_by(DiscoveryPick.rank)).scalars().all()
    assert len(rows) == 3                      # 全量落库,不止 TopN
    assert rows[0].rank == 1
    assert [r.code for r in rows] == [c for c, _ in out]   # 落库顺序=返回顺序
    assert json.loads(rows[0].factors)         # factors 是合法 JSON


def test_run_qlib_discovery_overwrites_same_day():
    s = _session()
    frozen = FrozenFactors(as_of="2026-06-25", factors=["f1"], signs={"f1": 1.0},
                           weights={"f1": 1.0}, universe="investable", horizon=5,
                           source_report="r", metrics_at_freeze={})
    for _ in range(2):
        run_qlib_discovery(s, date(2026, 6, 25), frozen, ["A", "B"],
                           load_features_fn=_fake_features)
    rows = s.execute(select(DiscoveryPick)).scalars().all()
    assert len(rows) == 2                       # 重复跑同日不累积
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_qlib_discovery_run.py -v`
Expected: FAIL with `ImportError: cannot import name 'run_qlib_discovery'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/discovery/qlib_provider.py`:

```python
import json
from datetime import date
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import DiscoveryPick
from app.factors.frozen import FrozenFactors
from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument


def load_features(insts: list[str], factors: list[str], as_of: date,
                  lookback: int) -> pd.DataFrame:
    """qlib D.features 薄包装:按 as_of 回溯 lookback 交易日取数,
    返回列名=因子名的面板。需先 init_qlib()。"""
    from qlib.data import D
    cal = [c.date() for c in D.calendar(end_time=as_of)]
    start = cal[-lookback] if len(cal) >= lookback else cal[0]
    end = cal[-1]
    fields = [FACTOR_LIBRARY[n] for n in factors]
    df = D.features(insts, fields, start_time=start, end_time=end)
    df.columns = factors
    return to_datetime_instrument(df)


def run_qlib_discovery(session: Session, as_of: date, frozen: FrozenFactors,
                       insts: list[str], *, lookback: int = 60,
                       load_features_fn=load_features) -> list[tuple[str, float]]:
    """对全市场用冻结因子打分,取最新截面降序,全量覆盖写 DiscoveryPick。"""
    panel = load_features_fn(insts, frozen.factors, as_of, lookback)
    score_df = score_panel(panel, frozen.signs)
    section = latest_section(score_df)
    ranked = [(str(code), float(sc)) for code, sc in section.items()]
    session.execute(delete(DiscoveryPick).where(DiscoveryPick.as_of == as_of))
    for i, (code, sc) in enumerate(ranked, 1):
        session.add(DiscoveryPick(as_of=as_of, code=code, rank=i, score=sc,
                                  factors=json.dumps({"composite": sc})))
    session.commit()
    return ranked
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_qlib_discovery_run.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/discovery/qlib_provider.py backend/tests/test_qlib_discovery_run.py
git commit -m "feat(discovery): qlib composite scoring writes full DiscoveryPick ranking"
```

---

### Task 5: 冻结脚本(从最新挖掘报告产出 frozen_composite.json)

**Files:**
- Create: `backend/scripts/freeze_factors.py`
- Test: `backend/tests/test_freeze_factors_script.py`

**Interfaces:**
- Consumes: Task 2 `select_frozen`、Task 1 `save_frozen`;复用 `run_composite_backtest.py` 里读报告与算相关的逻辑(`_latest_mining_report` 同款 glob、`D.features`+`cs_zscore`+`corr`)
- Produces:
  - `frozen_path(settings) -> Path` — `<qlib_data_dir 父目录>/factors/frozen_composite.json`
  - `freeze(session_settings, *, universe="investable", horizon=5, threshold=0.8) -> FrozenFactors` — 载入最新 `factor_mining_*.json`,取 robust 因子名与 `rank_ic_oos`,用 qlib 算截面 z-score 相关矩阵,`select_frozen` 选定后 `save_frozen` 落盘并返回
  - CLI:`python scripts/freeze_factors.py` 跑一次,打印冻结的因子数与路径

- [ ] **Step 1: Write the failing test**

测试只覆盖纯逻辑路径(`frozen_path` 拼接 + `select_frozen` 已在 Task 2 测),避免依赖 qlib:

```python
# backend/tests/test_freeze_factors_script.py
from pathlib import Path
from scripts.freeze_factors import frozen_path


class _S:
    qlib_data_dir = "/data/proj/data/qlib_cn"


def test_frozen_path_under_factors_dir():
    p = frozen_path(_S())
    assert p == Path("/data/proj/data/factors/frozen_composite.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_freeze_factors_script.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.freeze_factors'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/scripts/freeze_factors.py
"""从最新 factor_mining_*.json 产出冻结复合因子产物 frozen_composite.json。
复用 run_composite_backtest 的选因子逻辑:robust 因子 -> 截面 z-score 相关去重 -> 等权。"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from app.config import get_settings
from app.backtest.qlib_data import init_qlib
from app.quant.ml_pipeline import cs_zscore
from app.quant.factor_mine import FACTOR_LIBRARY, to_datetime_instrument
from app.factors.frozen import select_frozen, save_frozen, FrozenFactors


def frozen_path(settings) -> Path:
    return Path(settings.qlib_data_dir).resolve().parent / "factors" / "frozen_composite.json"


def _latest_mining(reports_dir: Path) -> dict:
    files = [f for f in sorted(glob.glob(str(reports_dir / "factor_mining_*.json")))
             if "smoke" not in f]
    if not files:
        raise FileNotFoundError("找不到 factor_mining_*.json,先跑 run_factor_mining.py")
    return json.loads(Path(files[-1]).read_text())


def freeze(settings, *, universe="investable", horizon=5, threshold=0.8) -> FrozenFactors:
    init_qlib(settings.qlib_data_dir)
    from qlib.data import D
    reports_dir = Path(settings.qlib_data_dir).resolve().parent / "reports"
    mining = _latest_mining(reports_dir)
    robust = mining["robust_factors"]                  # 已按 |IR| 降序
    ranked = [r["name"] for r in robust]
    rank_ic = {r["name"]: r["rank_ic_oos"] for r in robust}
    insts = D.list_instruments(D.instruments(universe), as_list=True)
    end = D.calendar()[-1]
    fields = [FACTOR_LIBRARY[n] for n in ranked]
    df = D.features(insts, fields, start_time="2025-01-01", end_time=end)
    df.columns = ranked
    df = to_datetime_instrument(df)
    z = pd.DataFrame({n: cs_zscore(df[n]) for n in ranked})
    corr = z.corr()
    ff = select_frozen(ranked, rank_ic, corr, universe=universe, horizon=horizon,
                       source_report=mining.get("as_of", "unknown"),
                       as_of=str(end.date()),
                       metrics=mining.get("composite_metrics", {}), threshold=threshold)
    save_frozen(ff, frozen_path(settings))
    return ff


def main():
    s = get_settings()
    ff = freeze(s)
    print(f"冻结 {len(ff.factors)} 个因子 -> {frozen_path(s)}", flush=True)
    print(f"  {ff.factors}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_freeze_factors_script.py -v`
Expected: PASS

- [ ] **Step 5: Generate the real artifact + commit**

```bash
cd backend && .venv/bin/python scripts/freeze_factors.py
# 预期打印 "冻结 18 个因子 -> .../data/factors/frozen_composite.json"
git add backend/scripts/freeze_factors.py backend/tests/test_freeze_factors_script.py
git commit -m "feat(factors): freeze_factors script produces frozen_composite.json from latest mining report"
```

注:生成的 `data/factors/frozen_composite.json` 是否纳入版本控制,按项目对 `data/` 的现有 .gitignore 习惯处理(若 data/ 已忽略则不强行加)。

---

### Task 6: run_discovery 接入 qlib 源(默认 qlib,替掉动量)

**Files:**
- Modify: `backend/scripts/run_discovery.py`
- Test: `backend/tests/test_run_discovery_source.py`

**Interfaces:**
- Consumes: Task 4 `run_qlib_discovery`、Task 5 `frozen_path`、Task 1 `load_frozen`
- Produces:
  - `run_discovery.py` 新增 `--source {qlib,momentum}`,**默认 qlib**;`--top-n` 仅影响打印,DiscoveryPick 仍全量落库
  - qlib 路径:`init_qlib` → `load_frozen(frozen_path(s))` → `D.list_instruments(D.instruments(frozen.universe))` → `run_qlib_discovery(session, as_of, frozen, insts)`
  - momentum 路径:保留原有 `DiscoveryRunner`+`MomentumProvider` 不变

- [ ] **Step 1: Write the failing test**

argparse 默认值校验(不跑 qlib):

```python
# backend/tests/test_run_discovery_source.py
from scripts.run_discovery import build_parser


def test_source_defaults_to_qlib():
    args = build_parser().parse_args([])
    assert args.source == "qlib"


def test_source_can_select_momentum():
    args = build_parser().parse_args(["--source", "momentum"])
    assert args.source == "momentum"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_run_discovery_source.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_parser'` 或 `AttributeError: source`

- [ ] **Step 3: Write minimal implementation**

把 `run_discovery.py` 里现有的 `argparse` 抽成 `build_parser()`,加 `--source`,并按源分支。改写后的关键部分:

```python
# backend/scripts/run_discovery.py  —— 关键改动
import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None, help="YYYY-MM-DD; default = latest in DB")
    p.add_argument("--window", type=int, default=20)
    p.add_argument("--source", choices=["qlib", "momentum"], default="qlib")
    p.add_argument("--top-n", type=int, default=8, help="仅影响打印,落库为全量")
    p.add_argument("--with-research", action="store_true",
                   help="(momentum 源)挂入研报质化信号")
    return p


def main():
    args = build_parser().parse_args()
    engine = make_engine(); Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    store = QuoteStore(session)
    as_of = (date(*map(int, args.date.split("-"))) if args.date
             else store.trading_dates(date.today(), 1)[0])

    if args.source == "qlib":
        from app.config import get_settings
        from app.backtest.qlib_data import init_qlib
        from app.factors.frozen import load_frozen
        from app.discovery.qlib_provider import run_qlib_discovery
        from scripts.freeze_factors import frozen_path
        s = get_settings()
        init_qlib(s.qlib_data_dir)
        from qlib.data import D
        frozen = load_frozen(frozen_path(s))
        insts = D.list_instruments(D.instruments(frozen.universe), as_list=True)
        picks = run_qlib_discovery(session, as_of, frozen, insts)
        print(f"[qlib] {as_of} 全市场 {len(insts)} 只打分,落 {len(picks)} 条;Top{args.top_n}:")
        for code, score in picks[:args.top_n]:
            print(f"  {code}  {score:+.4f}")
        return

    # momentum 源:原有逻辑保留
    providers = [MomentumProvider()]
    if args.with_research:
        providers.append(ResearchSignalProvider(ResearchStore(session)))
    runner = DiscoveryRunner(session, QuoteStoreMarketHistory(store),
                             providers, DiscoveryScorer(top_n=args.top_n),
                             window=args.window)
    picks = runner.run(as_of)
    for code, score, raw in picks:
        print(code, round(score, 4))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_run_discovery_source.py -v`
Expected: PASS

- [ ] **Step 5: Integration smoke + commit**

```bash
cd backend && .venv/bin/python scripts/run_discovery.py --source qlib --top-n 8
# 预期打印当日 Top8 代码与 composite 分(降序),与离线回测同日排序一致
git add backend/scripts/run_discovery.py backend/tests/test_run_discovery_source.py
git commit -m "feat(discovery): run_discovery --source qlib (default), replaces momentum selection"
```

---

### Task 7: 集成测试 — qlib 端到端打分(真实数据)

**Files:**
- Test: `backend/tests/test_qlib_discovery_integration.py`

**Interfaces:**
- Consumes: Task 4 `load_features`/`run_qlib_discovery`、Task 5 `freeze`/`frozen_path`

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/test_qlib_discovery_integration.py
from datetime import date
from pathlib import Path
import pytest
from app.config import get_settings
from app.factors.frozen import load_frozen


pytestmark = pytest.mark.integration


def _has_qlib_data() -> bool:
    s = get_settings()
    return Path(s.qlib_data_dir, "calendars").exists()


@pytest.mark.skipif(not _has_qlib_data(), reason="需要本地 data/qlib_cn")
def test_load_features_returns_panel_for_frozen_factors():
    from app.backtest.qlib_data import init_qlib
    from app.discovery.qlib_provider import load_features
    from scripts.freeze_factors import frozen_path
    s = get_settings()
    init_qlib(s.qlib_data_dir)
    from qlib.data import D
    frozen = load_frozen(frozen_path(s))
    insts = D.list_instruments(D.instruments(frozen.universe), as_list=True)[:50]
    as_of = D.calendar()[-1].date()
    panel = load_features(insts, frozen.factors, as_of, lookback=40)
    assert list(panel.columns) == frozen.factors
    assert panel.index.names == ["datetime", "instrument"]
    assert len(panel) > 0
```

- [ ] **Step 2: Run integration test**

Run: `cd backend && .venv/bin/pytest tests/test_qlib_discovery_integration.py -v -m integration`
Expected: PASS(本地有 data/qlib_cn 时);无数据时 SKIP

- [ ] **Step 3: Run full Phase 1 suite + commit**

```bash
cd backend && .venv/bin/pytest tests/test_frozen_factors.py tests/test_frozen_select.py \
  tests/test_qlib_compose_score.py tests/test_qlib_discovery_run.py \
  tests/test_freeze_factors_script.py tests/test_run_discovery_source.py -v
# 预期全绿
git add backend/tests/test_qlib_discovery_integration.py
git commit -m "test(discovery): qlib end-to-end scoring integration test"
```

---

## Self-Review

**Spec coverage(对照 spec §5 Phase 1):**
- §5.1 冻结产物结构 → Task 1(I/O)+ Task 5(生成真实产物)✓
- §5.2 QlibCompositeProvider 每日打分(加载产物→D.features→cs_zscore→composite_score→最新截面→排序→DiscoveryPick)→ Task 3(打分/截面)+ Task 4(取数+落库)✓
- §5.3 完全替掉动量(`--source qlib` 默认,不经百分位)→ Task 6 ✓
- §5.4 验收(同日截面与回测不漂移)→ Task 6 Step 5 smoke + Task 7 集成 ✓
- "只存因子名不存表达式" → Task 1/5 只写 factors 名,表达式取自 FACTOR_LIBRARY ✓
- "全量落库不止 TopN" → Task 4 测试断言 len==全量 ✓

**Placeholder scan:** 无 TBD/TODO;每个代码步含完整代码;命令含预期输出。✓

**Type consistency:** `FrozenFactors` 字段在 Task 1 定义,Task 2/4/5/6 一致使用;`load_features(insts, factors, as_of, lookback)` 签名 Task 4 定义,集成测试(Task 7)与 `run_qlib_discovery` 内部调用一致;`run_qlib_discovery(session, as_of, frozen, insts, *, lookback, load_features_fn)` 签名在 Task 4 定义、Task 6 调用一致;`frozen_path(settings)` 在 Task 5 定义、Task 6 引用一致;`select_frozen(...)` 签名 Task 2 定义、Task 5 调用一致。✓

**lookback 取数:** `load_features` 按 `as_of` 用 `D.calendar(end_time=as_of)[-lookback]` 回溯起始日,`run_qlib_discovery` 透传 `as_of`/`lookback`;单测用 `_fake_features(insts, factors, as_of, lookback)` 注入,签名一致。✓
