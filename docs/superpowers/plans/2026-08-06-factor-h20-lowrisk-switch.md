# 因子换代:h20 低风险异象 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把生产因子从 h5 价量反转换成 h20 低风险异象(创业板不变),并加一道"组合分数正向预测 h20 收益"的验证闸。

**Architecture:** 新增 `Settings.discovery_horizon` 作横周期单一事实源,挖掘/冻结脚本默认从它取(比照现成的 `discovery_universe` 模式,防 `run_remine` 静默切回 h5);新增验证脚本复用生产打分函数把关;换代后辩论话术从"超跌反弹"改为低风险口径。选股打分链路(`composite_score`/`score_panel`)无需改代码——换 frozen 产物即换策略。

**Tech Stack:** Python 3.11、pydantic-settings、qlib、pandas、pytest。

## Global Constraints

- 宇宙固定创业板 `cyb`,本轮不改。
- 目标持有/预测周期 `discovery_horizon = 20`。
- 验证闸通过条件:复合分数对 h20 远期收益 **OOS RankIC ≥ +0.05** 且**最高分层收益 ≥ 最低分层收益**。
- 打分口径必须与生产一致:一律复用 `app.quant.factor_compose.composite_score`(按日截面 z-score × 符号、跨因子等权平均)。
- **不改交易执行**:0.6 置信度门槛、仓位、退出逻辑本轮不动。本轮改完不会自动买入(预期,非缺陷)。
- TDD;每个可测单元一独立 test/impl/commit 循环。
- 后端测试命令:`cd backend && .venv/bin/python -m pytest <file> -q`。

---

### Task 1: 横周期单一事实源(config + 两脚本默认跟随)

**Files:**
- Modify: `backend/app/config.py`(新增字段 + `resolve_horizon` 帮助函数;更新 `buy_trend_window` 注释)
- Modify: `backend/scripts/run_factor_mining.py`(`--horizon` 默认 None → resolve)
- Modify: `backend/scripts/freeze_factors.py`(`freeze(horizon=None)` → resolve;`--horizon` CLI)
- Test: `backend/tests/test_config_phase2.py`、`backend/tests/test_freeze_factors_script.py`、新建 `backend/tests/test_run_factor_mining_args.py`

**Interfaces:**
- Produces:
  - `app.config.Settings.discovery_horizon: int = 20`
  - `app.config.resolve_horizon(cli_value: int | None, settings) -> int`(cli_value 非 None 时用它,否则 `settings.discovery_horizon`)
  - `scripts.run_factor_mining.build_parser() -> argparse.ArgumentParser`(`--horizon` 默认 None)
  - `scripts.freeze_factors.build_parser() -> argparse.ArgumentParser`(`--horizon` 默认 None)
  - `scripts.freeze_factors.freeze(settings, *, universe=None, horizon=None, threshold=0.8, report_path=None)`

- [ ] **Step 1: 写失败测试(config)**

在 `backend/tests/test_config_phase2.py` 末尾追加:

```python
def test_discovery_horizon_default_20():
    from app.config import Settings
    assert Settings().discovery_horizon == 20


def test_resolve_horizon_prefers_cli_then_settings():
    from app.config import Settings, resolve_horizon
    s = Settings()
    assert resolve_horizon(5, s) == 5          # 显式 CLI 值优先
    assert resolve_horizon(None, s) == 20      # 缺省回落到 settings
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config_phase2.py -q`
Expected: FAIL(`AttributeError: 'Settings' object has no attribute 'discovery_horizon'` / `ImportError: resolve_horizon`)

- [ ] **Step 3: 实现 config 改动**

在 `backend/app/config.py` 的 `Settings` 类中,`discovery_universe` 字段之后加一行:

```python
    discovery_horizon: int = 20            # 生产因子持有/预测周期(T+1买、T+1+h卖的h日)
                                           # 挖掘/冻结默认跟随此值,防脚本静默用旧的 h5
```

把 `buy_trend_window` 现有注释中这句(已不成立):
`# 当前 frozen 因子是短周期反转型(专挑超跌),` 改为:
`# 当前 frozen 因子是 h20 低风险异象型(低波/低换手/低流动),`

在 `Settings` 类定义之后(文件模块级)加帮助函数:

```python
def resolve_horizon(cli_value, settings) -> int:
    """CLI 显式值优先,缺省(None)回落到 settings.discovery_horizon。"""
    return cli_value if cli_value is not None else settings.discovery_horizon
```

- [ ] **Step 4: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config_phase2.py -q`
Expected: PASS

- [ ] **Step 5: 写失败测试(run_factor_mining 参数默认)**

新建 `backend/tests/test_run_factor_mining_args.py`:

```python
def test_horizon_arg_defaults_to_none():
    # 默认 None,好让 main 回落到 settings.discovery_horizon(防写死 h5)
    from scripts.run_factor_mining import build_parser
    assert build_parser().parse_args([]).horizon is None
    assert build_parser().parse_args(["--horizon", "10"]).horizon == 10
```

- [ ] **Step 6: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_run_factor_mining_args.py -q`
Expected: FAIL(`ImportError: cannot import name 'build_parser'`)

- [ ] **Step 7: 实现 run_factor_mining 改动**

在 `backend/scripts/run_factor_mining.py` 中,把 `main()` 里内联构造 parser 的部分抽成模块级 `build_parser()`,并把 `--horizon` 默认改为 `None`;`main()` 解析后用 `resolve_horizon` 回落。改动:

将现有
```python
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default=None,
                   help="缺省用 settings.discovery_universe(生产宇宙,run_remine 依赖此默认)")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--is-start", default="2022-01-01")
    p.add_argument("--split", default="2025-01-01")   # IS < split <= OOS
    p.add_argument("--ic-min", type=float, default=0.02)
    p.add_argument("--ir-min", type=float, default=0.3)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()

    s = get_settings()
    if args.universe is None:
        args.universe = s.discovery_universe
```
改为
```python
def build_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--universe", default=None,
                   help="缺省用 settings.discovery_universe(生产宇宙,run_remine 依赖此默认)")
    p.add_argument("--horizon", type=int, default=None,
                   help="缺省用 settings.discovery_horizon(防写死旧周期)")
    p.add_argument("--is-start", default="2022-01-01")
    p.add_argument("--split", default="2025-01-01")   # IS < split <= OOS
    p.add_argument("--ic-min", type=float, default=0.02)
    p.add_argument("--ir-min", type=float, default=0.3)
    p.add_argument("--smoke", action="store_true")
    return p


def main():
    args = build_parser().parse_args()
    s = get_settings()
    if args.universe is None:
        args.universe = s.discovery_universe
    args.horizon = resolve_horizon(args.horizon, s)
```

并把顶部导入 `from app.config import get_settings` 改为 `from app.config import get_settings, resolve_horizon`。

- [ ] **Step 8: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_run_factor_mining_args.py -q`
Expected: PASS

- [ ] **Step 9: 写失败测试(freeze_factors)**

在 `backend/tests/test_freeze_factors_script.py` 末尾追加:

```python
def test_freeze_horizon_default_none_and_cli_present():
    import inspect
    from scripts.freeze_factors import freeze, build_parser
    # freeze 的 horizon 默认必须是 None(好回落到 settings),不能写死 5
    assert inspect.signature(freeze).parameters["horizon"].default is None
    # CLI 暴露 --horizon,默认 None
    ns = build_parser().parse_args([])
    assert ns.horizon is None
    assert build_parser().parse_args(["--horizon", "20"]).horizon == 20
```

- [ ] **Step 10: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_freeze_factors_script.py -q`
Expected: FAIL(`ImportError: cannot import name 'build_parser'` 或签名默认为 5)

- [ ] **Step 11: 实现 freeze_factors 改动**

在 `backend/scripts/freeze_factors.py`:

顶部导入改 `from app.config import get_settings` → `from app.config import get_settings, resolve_horizon`。

`freeze` 签名与首行:
```python
def freeze(settings, *, universe=None, horizon=None, threshold=0.8,
           report_path=None) -> FrozenFactors:
    universe = universe or settings.discovery_universe
    horizon = resolve_horizon(horizon, settings)
    init_qlib(settings.qlib_data_dir)
```

把 `main()` 里的 parser 抽成 `build_parser()` 并加 `--horizon`:
```python
def build_parser():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--report", default="",
                   help="显式指定 factor_mining_*.json;缺省取目录最新非 smoke")
    p.add_argument("--universe", default=None,
                   help="缺省用 settings.discovery_universe(生产宇宙)")
    p.add_argument("--horizon", type=int, default=None,
                   help="缺省用 settings.discovery_horizon")
    return p


def main():
    args = build_parser().parse_args()
    s = get_settings()
    ff = freeze(s, universe=args.universe, horizon=args.horizon,
                report_path=args.report or None)
    print(f"冻结 {len(ff.factors)} 个因子(universe={ff.universe} horizon={ff.horizon}) "
          f"-> {frozen_path(s)}", flush=True)
    print(f"  {ff.factors}", flush=True)
```

- [ ] **Step 12: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_freeze_factors_script.py tests/test_config_phase2.py tests/test_run_factor_mining_args.py -q`
Expected: PASS(全部)

- [ ] **Step 13: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/app/config.py backend/scripts/run_factor_mining.py backend/scripts/freeze_factors.py backend/tests/test_config_phase2.py backend/tests/test_freeze_factors_script.py backend/tests/test_run_factor_mining_args.py
git commit -m "feat: discovery_horizon 单一事实源,挖掘/冻结默认跟随(默认h20)"
```

---

### Task 2: 组合对齐验证闸 `validate_frozen_alignment.py`

**Files:**
- Create: `backend/scripts/validate_frozen_alignment.py`
- Test: `backend/tests/test_validate_frozen_alignment.py`

**Interfaces:**
- Consumes: `app.quant.factor_compose.composite_score(panel, signs) -> DataFrame['score']`(生产打分函数);`app.backtest.factor.factor_report(score_frame, fwd_returns, layers=5) -> dict`(返回含 `rank_ic_mean`、`layer_returns`)。
- Produces:
  - `alignment_report(panel, signs, fwd_returns, layers=5) -> dict`,返回 `{"rank_ic": float, "layers": list[float], "passed": bool}`。
  - `passed = rank_ic >= 0.05 and layers[-1] >= layers[0]`。
  - CLI `main()`:加载 frozen、在其 universe/horizon 上取因子面板与远期收益、调 `alignment_report`、打印、通过 `sys.exit(0)` 否则 `sys.exit(1)`。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_validate_frozen_alignment.py`:

```python
import numpy as np
import pandas as pd
from scripts.validate_frozen_alignment import alignment_report


def _panel(sign_of_factor):
    # 造 40 天 × 30 只:未来收益 fwd 已知;因子 = sign_of_factor * fwd(+噪声)
    rng = np.random.RandomState(0)
    rows, fwd = [], {}
    dts = pd.date_range("2025-01-01", periods=40, freq="D")
    for dt in dts:
        for i in range(30):
            r = rng.normal()
            rows.append((dt, f"S{i}", sign_of_factor * r + 0.01 * rng.normal()))
            fwd[(dt, f"S{i}")] = r
    idx = pd.MultiIndex.from_tuples([(d, c) for d, c, _ in rows],
                                    names=["datetime", "instrument"])
    panel = pd.DataFrame({"f1": [v for _, _, v in rows]}, index=idx)
    ret = pd.Series({k: v for k, v in fwd.items()})
    ret.index = ret.index.set_names(["datetime", "instrument"])
    return panel, ret


def test_alignment_passes_when_score_predicts_returns():
    panel, ret = _panel(sign_of_factor=1.0)      # 因子与未来收益正相关
    rep = alignment_report(panel, {"f1": 1.0}, ret)
    assert rep["rank_ic"] > 0.05
    assert rep["layers"][-1] >= rep["layers"][0]
    assert rep["passed"] is True


def test_alignment_fails_when_score_anti_predicts():
    panel, ret = _panel(sign_of_factor=-1.0)     # 符号取+1 但因子实际反向 -> 应失败
    rep = alignment_report(panel, {"f1": 1.0}, ret)
    assert rep["passed"] is False
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_validate_frozen_alignment.py -q`
Expected: FAIL(`ModuleNotFoundError: scripts.validate_frozen_alignment`)

- [ ] **Step 3: 实现脚本**

新建 `backend/scripts/validate_frozen_alignment.py`:

```python
"""换代把关:加载 frozen_composite.json,用生产打分函数 composite_score 重算
复合分数,验证它【正向】预测 horizon 日远期收益(OOS RankIC>=+0.05 且分层单调
方向正确)。不通过则退出码 1。防再次上线一个分数与收益反向的组合。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.quant.factor_compose import composite_score
from app.backtest.factor import factor_report

RANK_IC_MIN = 0.05


def alignment_report(panel, signs, fwd_returns, layers: int = 5) -> dict:
    score = composite_score(panel, signs)          # 生产同一函数
    rep = factor_report(score, fwd_returns, layers=layers)
    lyr = rep["layer_returns"]
    ric = rep["rank_ic_mean"]
    passed = ric >= RANK_IC_MIN and (len(lyr) >= 2 and lyr[-1] >= lyr[0])
    return {"rank_ic": ric, "layers": lyr, "passed": passed}


def main():
    from app.config import get_settings
    from app.backtest.qlib_data import init_qlib
    from app.factors.frozen import load_frozen
    from app.quant.factor_mine import FACTOR_LIBRARY, label_expr, to_datetime_instrument
    from scripts.freeze_factors import frozen_path

    s = get_settings()
    ff = load_frozen(frozen_path(s))
    init_qlib(s.qlib_data_dir)
    from qlib.data import D
    end = D.calendar()[-1]
    insts = D.list_instruments(D.instruments(ff.universe), as_list=True)
    fields = [FACTOR_LIBRARY[n] for n in ff.factors] + [label_expr(ff.horizon)]
    df = D.features(insts, fields, start_time="2025-01-01", end_time=end)
    df.columns = list(ff.factors) + ["label"]
    df = to_datetime_instrument(df)
    panel = df[list(ff.factors)]
    rep = alignment_report(panel, ff.signs, df["label"])
    print(f"universe={ff.universe} horizon={ff.horizon} "
          f"n_factors={len(ff.factors)}", flush=True)
    print(f"OOS RankIC={rep['rank_ic']:+.4f}  分层收益={[round(x,4) for x in rep['layers']]}",
          flush=True)
    print(f"ALIGNMENT {'PASS' if rep['passed'] else 'FAIL'} "
          f"(阈值 RankIC>={RANK_IC_MIN} 且 高分层>=低分层)", flush=True)
    sys.exit(0 if rep["passed"] else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_validate_frozen_alignment.py -q`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/scripts/validate_frozen_alignment.py backend/tests/test_validate_frozen_alignment.py
git commit -m "feat: 冻结组合对齐验证闸(分数须正向预测远期收益)"
```

---

### Task 3: 辩论话术改低风险口径

**Files:**
- Modify: `backend/scripts/daily_full.py:126-134`(`_reversal_thesis` → `_lowrisk_thesis`)、调用点 `:195-196`
- Modify: `backend/app/decision/agents.py`(量价/多头/交易员 三处"超跌反弹"条件分支)
- Test: 新建 `backend/tests/test_lowrisk_thesis.py`

**Interfaces:**
- Produces: `daily_full._lowrisk_thesis(closes) -> str | None`(< 5 根收盘返回 None;否则返回含"低波动/低风险"字样、不含"超跌反弹"的一句话)。

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_lowrisk_thesis.py`:

```python
def test_lowrisk_thesis_text_and_none():
    import scripts.daily_full as df
    assert df._lowrisk_thesis([10.0]) is None            # 数据不足
    txt = df._lowrisk_thesis([10.0, 10.1, 9.9, 10.0, 10.05, 10.02])
    assert txt is not None
    assert "低风险" in txt or "低波动" in txt
    assert "超跌反弹" not in txt


def test_agents_prompts_switched_to_lowrisk():
    from app.decision.agents import ROLES
    blob = "".join(ROLES.values())
    assert "超跌反弹" not in blob                          # 旧口径清干净
    assert "低波动" in blob or "低风险" in blob            # 新口径已注入
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_lowrisk_thesis.py -q`
Expected: FAIL(`AttributeError: module 'scripts.daily_full' has no attribute '_lowrisk_thesis'`)

- [ ] **Step 3: 实现 daily_full 改动**

把 `backend/scripts/daily_full.py` 的 `_reversal_thesis` 函数(126-134 行)整体替换为:

```python
    def _lowrisk_thesis(closes):
        if len(closes) < 5:
            return None
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        vol_ann = (var ** 0.5) * (252 ** 0.5) * 100        # 年化波动率(%)
        return (f"低风险异象因子选出:近期日收益年化波动率约{vol_ann:.0f}%(偏低)、"
                f"走势清淡。入选理由是低波动/低换手/低流动性特征,请评估其作为稳健"
                f"低波标的的持有价值(平稳缩量、无暴涨暴跌),而非动量突破或超跌反弹。")
```

把调用点(195-196 行附近):
```python
            # 反转策略视角只挂给买入候选(非持仓);持仓的去留另有逻辑
            strategy = None if h else _reversal_thesis(closes)
```
改为:
```python
            # 低风险策略视角只挂给买入候选(非持仓);持仓的去留另有逻辑
            strategy = None if h else _lowrisk_thesis(closes)
```

- [ ] **Step 4: 实现 agents.py 改动**

在 `backend/app/decision/agents.py` 的 `ROLES` 中改三处:

「量价分析师」值里
```
"若为短周期反转/超跌反弹策略,则本股近期下跌本身就是入选理由,你的任务不是判断上升趋势是否延续,"
"而是评估**超跌反弹的胜算**——是否出现缩量止跌、下影企稳、跌速衰竭、超跌程度(偏离均线幅度);"
"只有仍在加速下跌且毫无企稳迹象的才算真飞刀。简明给出看法。"
```
改为
```
"若为低风险异象策略,则本股因低波动/低换手/清淡流动被选入,你的任务不是判断上升趋势,"
"而是评估其**低波稳健度**——是否走势平稳、缩量、无暴涨暴跌、无异常放量出货迹象;"
"波动骤升或放量破位的才需警惕。简明给出看法。"
```

「多头研究员」值里
```
"若 brief「选股逻辑」为超跌反弹,则围绕反弹胜算(超跌幅度、企稳迹象、赔率)展开,而非要求已处上升趋势。"
```
改为
```
"若 brief「选股逻辑」为低风险异象,则围绕低波稳健(波动率低、走势平稳、下行风险小)论证持有价值,而非要求上升趋势。"
```

「交易员」值里
```
"**若 brief「选股逻辑」为短周期反转/超跌反弹**:近期下跌是策略入选理由,不要仅因近期下跌就否决买入;"
"在超跌且出现企稳迹象(缩量止跌/跌速衰竭)时应给 BUY;仅当加速下跌毫无企稳时才 HOLD 回避。"
```
改为
```
"**若 brief「选股逻辑」为低风险异象**:低波动/清淡是策略入选理由,不要因缺乏上涨动量就否决买入;"
"在走势平稳、无放量破位时应给 BUY;仅当波动骤升或放量出货时才 HOLD 回避。"
```

- [ ] **Step 5: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_lowrisk_thesis.py -q`
Expected: PASS(2 passed)

- [ ] **Step 6: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/scripts/daily_full.py backend/app/decision/agents.py backend/tests/test_lowrisk_thesis.py
git commit -m "feat: 辩论话术从超跌反弹改为 h20 低风险异象口径"
```

---

### Task 4:(运维,由控制者执行,非代码子代理)执行换代并验证

> 本任务不写代码,是数据产物操作 + 长任务运行。由控制者按下列命令执行;验收=验证闸通过且全测试绿。data/ 为 gitignored,产物不进 git。

- [ ] **Step 1: 备份当前 h5 组合**

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend
mkdir -p data/factors/archive
cp data/factors/frozen_composite.json data/factors/archive/frozen_composite_2026-08-06_h5reversal.json
```

- [ ] **Step 2: 重挖创业板 h20**(后台约15分钟;universe/horizon 均走默认=cyb/20)

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend
setsid nice -n 15 .venv/bin/python scripts/run_factor_mining.py > /tmp/remine_h20.log 2>&1 &
```
用 until-loop 等 `FACTOR_MINING_DONE` 或 `Traceback` 出现;确认报告落在 `data/reports/factor_mining_<date>_h20.json`。

- [ ] **Step 3: 重新冻结**(走默认,读最新 h20 报告)

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend
.venv/bin/python scripts/freeze_factors.py
```
Expected: 打印 `冻结 N 个因子(universe=cyb horizon=20)`。

- [ ] **Step 4: 跑验证闸**

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend
.venv/bin/python scripts/validate_frozen_alignment.py; echo "exit=$?"
```
Expected: `ALIGNMENT PASS`、`exit=0`、OOS RankIC ≥ +0.05(实测目标 ~+0.126)。
**若 FAIL**:不上线,`cp` 备份文件覆盖回 `frozen_composite.json` 回滚,并回报 controller 复查因子集。

- [ ] **Step 5: 全后端测试绿**

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend && .venv/bin/python -m pytest tests/ -q
```
Expected: all passed。

- [ ] **Step 6: 重构建前端不需要**(本轮无前端改动);重启后端使新 frozen 生效见 [[ashare-deploy-serving]]:

```bash
# 后端读取 frozen 是每次选股时 load,故夜链下一轮自动生效;如需立刻:重启 uvicorn(setsid)
```

---

## Self-Review

**Spec 覆盖**:
- discovery_horizon 单一源 → Task 1 ✓
- 挖掘/冻结默认跟随 → Task 1 ✓
- 验证闸(复用 composite_score,RankIC≥+0.05 且分层方向) → Task 2 ✓
- 话术改低风险(daily_full + agents 三处) → Task 3 ✓
- 备份/重挖/重冻结/验证/回滚 → Task 4 ✓
- 非目标(不改交易执行) → 计划未触碰 runner/门槛/退出 ✓
- 打分链路无需改代码 → 计划未改 composite_score/score_panel ✓

**占位符扫描**:无 TBD/TODO;每个代码步都给了完整代码。

**类型一致性**:`resolve_horizon(cli_value, settings)` 在 config 定义、mining/freeze 引用一致;`alignment_report(panel, signs, fwd_returns, layers=5)` 返回 `{rank_ic, layers, passed}` 与测试断言一致;`_lowrisk_thesis(closes)` 签名与调用点、测试一致;`factor_report` 返回键 `rank_ic_mean`/`layer_returns` 与实际实现(`app/backtest/factor.py`)一致。

**范围**:单一子系统(因子信号层),一个计划即可,无需拆分。
