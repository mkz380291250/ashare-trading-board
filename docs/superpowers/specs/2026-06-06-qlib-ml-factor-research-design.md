# Qlib 机器学习因子研究流水线 — 设计文档

日期:2026-06-06
分支(拟):`feat/qlib-ml-factor`

## Context(为什么做)

现状:每日定时批(`scripts/daily_full.py`)只做"行情更新 + qlib 数据 dump + 跟踪清单指标刷新",**没有任何机器学习选股**。真正的全市场打分用的是手算四因子(动量/换手/量比/突破,`app/discovery/`),且只在手动跑 `run_discovery.py` 时执行,没进每日定时;qlib 数据已建好(`data/qlib_cn`,233M)却只被回测用,**没有训练过任何 ML 模型**。

用户目标:把 qlib 真正"跑起来",基于已有数据(源自 tushare)做机器学习拟合,回测选出最优因子组合,参考热门因子。

经核对确定的范围(用户拍板 1A→2A→3A→4A):
- **因子来源**:qlib 内置 **Alpha158**(158 个量价因子,纯 OHLCV,即开即用,涵盖主流"热门因子":动量/反转/波动/量能/K线形态)。基本面/资金流自建因子(tushare 回填)**本期不做**,留作 v2。
- **股票池**:全市场去 ST / 去次新。
- **预测标签**:未来 5 日收益。
- **模型**:LightGBM 单模型(qlib 标配,输出因子重要性)。

数据基础(已确认):日线 2021-01-04 ~ 2026-06-05,762 个交易日 × 5714 只票(405 万行);qlib 0.9.7 + Alpha158 + LGBModel + lightgbm 4.6 全部可用。

## 目标产物

1. 一个可重复运行的 ML 研究流水线:**因子 → 标注 → 训练 → 预测 → 评估 → 回测 → 选最优因子组合**。
2. 输出报告:全因子单因子 IC 表、模型预测 IC/RankIC/IR、LightGBM 因子重要性排名、最优因子子集 + 其回测年化/夏普/最大回撤。
3. 持久化:训练好的模型 + 报告(json/markdown),复用现有 `BacktestStore` 落库回测结果。

非目标(本期不做):基本面/资金流自建因子、接入每日定时批做实盘选股、前端展示。这些是 v2,等基准跑出来再定。

## 复用现有(不重造轮子)

- `data/qlib_cn` qlib bin 数据(已建)+ `app/backtest/qlib_data.py:init_qlib()`
- `app/backtest/factor.py:factor_report()` —— IC / RankIC / IR / 分层收益,直接用于评估模型预测和单因子
- `app/backtest/strategy.py:run_strategy_backtest()` —— qlib TopkDropoutStrategy 回测(成本/年化/回撤/超额),喂模型预测分即可
- `app/backtest/store.py:BacktestStore` —— 回测结果落库
- `app/backtest/symbols.py:to_qlib_symbol / from_qlib_symbol`

## 新增组件

### 1. 投资域构建 `scripts/build_universe.py`
- 拉 tushare `stock_basic`(name + list_date,单次调用,便宜)。
- 规则:剔除 list_date 距 as_of 不足 **N=120** 个自然日的次新;剔除当前名称含 "ST/\*ST" 的票。
- 产出 qlib instruments 文件 `data/qlib_cn/instruments/investable.txt`(格式:`symbol\tstart\tend`)。
- **已知局限**:ST 判定用当前名称(非 point-in-time),历史上曾 ST 后摘帽的票会被当前状态误判。v2 用 tushare `namechange` 做时点 ST。文档中显式标注,不静默。

### 2. ML 流水线 `app/quant/ml_pipeline.py`(新包 `app/quant/`)
- `build_dataset(universe, train/valid/test 时间段, label_horizon=5)`:用 qlib `Alpha158` handler + `DatasetH`,label = `Ref($close,-6)/Ref($close,-1)-1`(T+1 买、T+6 卖,5 日收益)。
- `train_lgb(dataset)`:`LGBModel` 拟合,返回模型 + 预测分 DataFrame(MultiIndex datetime/instrument)。
- 时间切分(默认):train 2021-01~2024-06,valid 2024-07~2025-06,test 2025-07~2026-06。
- 纯函数化、依赖注入,便于测试 override。

### 3. 因子评估与最优组合 `app/quant/factor_select.py`
- 单因子扫描:对 Alpha158 每个因子算 RankIC/IR(复用 `factor_report`),出排名表。
- 模型因子重要性:LightGBM `feature_importance`。
- **选最优因子组合**:按重要性/IC 取若干候选子集(如 top-20 / top-50 / 按类别),分别重训 LGBM → 同口径回测 → 比较年化/夏普/回撤,选最优组合并给出理由。

### 4. 编排脚本 `scripts/run_ml_research.py`
- 串起:init qlib → 建投资域(若缺)→ build dataset → 训练 → 预测 → factor_report → 选最优组合 → 全量回测 → 存模型 + 写报告 `data/reports/ml_research_<asof>.{json,md}`。
- 命令行参数:`--start/--end/--horizon/--topk/--universe`,带 `--smoke`(短窗口冒烟)。

## 验证

- **单测**(pytest,放 `backend/tests/`):投资域过滤规则(造 stock_basic 假数据,验证 ST/次新被剔除);ml_pipeline 切分/标签构造逻辑(小型合成数据,不联网);factor_select 子集选择逻辑。
- **端到端冒烟**:`run_ml_research.py --smoke`(2024 一年、universe 取前 ~300 只)跑通,确认产出报告且 IC 非 NaN。
- **全量回归**:现有后端 214 测试保持全绿。
- **真实运行**:全窗口跑一次,人工核对报告里 RankIC 量级合理(月频 RankIC 均值 ~0.02-0.06 算正常)、回测曲线非爆炸。

## 工期与风险

- 估计:投资域 + 流水线 + 评估 + 编排 + 测试,约半天到一天实现;全量训练/回测跑批另需机时(LGBM 在 405 万行 × 158 因子上,单模型分钟级,选组合多模型对比可能十几分钟到半小时)。
- 风险:① qlib Alpha158 在全市场 5714 票上内存占用偏大——必要时按投资域裁剪 + 分块。② point-in-time ST 局限(见上)。③ 标签前视:已用 `Ref(-6)/Ref(-1)` 避免用到当日未来,切分严格按时间不重叠。

## v2(本期之后,等基准出来再定)
- 自建 tushare 基本面/资金流因子(需财务数据全市场回填入库)。
- 接入每日定时批:收盘后自动全市场打分出 top 名单。
- 前端展示 ML 选股结果。
