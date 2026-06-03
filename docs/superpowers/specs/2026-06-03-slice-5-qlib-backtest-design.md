# 切片5(回测) 设计:qlib 策略回测 + 因子分析框架

日期:2026-06-03
分支:`slice-5-backtest`(基于 `main`,已含切片0/1/2/3/4 + 题材选股器)

## 背景与目标

现有两个回测脚本(`backtest_dayang.py`/`backtest_screener.py`)是一次性的:单窗口、硬编码日期、信号逻辑各自重写(与线上 discovery/screener 漂移),统计意义弱(记忆已记:需改滚动多窗口)。

切片5(回测)用 **qlib 原生引擎**统一两件事:
1. **策略回测**:把系统现有信号(discovery 动量合成分 / 研报情绪分等)做成每日每股 score,喂 qlib `TopkDropoutStrategy` + backtest 引擎,出组合年化/夏普/最大回撤/换手,**以沪深300为基准**算超额收益/信息比率。验证线上信号的真实 edge。
2. **因子分析**:对同一 score(或 alpha 因子)跑 IC/RankIC + 分层收益,看因子预测力。

## 关键决策(brainstorm 已确认)

- **引擎 = qlib 原生**(非自建)。数据进 qlib bin,用 qlib 的 strategy/backtest/signal-analysis。
- **回测对象 = 策略回测 + 因子IC 两者都做**。
- **基准 = 沪深300**(tushare `index_daily` `000300.SH`),作为 instrument `SH000300` 并入 qlib 库,backtest `benchmark="SH000300"`。
- **score 来源**:复用线上 `MomentumProvider`/`DiscoveryScorer`(不重写信号逻辑),在日期区间上逐日跑出 score 帧;研报情绪分等其它信号同接口可插。
- **测试现实**:qlib 回测依赖大数据、难纯单测。**纯逻辑(score帧组装 / 代码↔qlib符号映射 / 指标解析 / 自算IC math)走 TDD 单测;qlib bin 构建 + qlib 回测/因子集成由小样本(几十只股)冒烟验证。**

## 前置数据任务(切片内 Task 0,重活)

QuoteStore(ashare.db,~4M 行 / 5700股 / 2021-2026)→ per-instrument CSV → qlib `dump_bin` → `data/qlib_cn`。

- 复用 `app/data/qlib_store.py` 的 `bars_to_dataframe`/`write_instrument_csv`(列:date/open/high/low/close/volume/factor)。qlib 用 `factor` 列做复权,价用不复权原始 OHLCV + factor —— 与本项目存储口径一致。
- **代码↔qlib符号映射**:`600519.SH ↔ SH600519`、`000001.SZ ↔ SZ000001`(qlib CN region 约定:交易所前缀大写 + 6位代码)。双向函数 `to_qlib_symbol` / `from_qlib_symbol`。
- **沪深300**:tushare `index_daily(ts_code="000300.SH")` 拉指数日线 → 同样写成 instrument `SH000300`(volume 用指数成交量或填 0,factor=1.0)。
- dump_bin:qlib 自带 `scripts/dump_bin.py`(`dump_all`)。封装成 `build_bin(csv_dir, qlib_dir)`,subprocess 调用(路径在冒烟 Task 联调确定);失败有清晰报错。
- 量大,经 `setsid` 后台跑(参考历史回填模式),完成标记 `QLIB_DUMP_DONE`。

## 架构:新模块 `backend/app/backtest/`

### 1. symbols.py — 代码↔qlib符号映射(纯函数,先做)
- `to_qlib_symbol("600519.SH") -> "SH600519"`;`from_qlib_symbol("SH600519") -> "600519.SH"`。
- 处理 .SH/.SZ/.BJ;非法输入抛 `ValueError`。

### 2. qlib_data.py — 数据构建 + 初始化
- `export_instrument_csvs(store, codes, start, end, out_dir) -> int`:逐 code 取 bars(QuoteStore)写 CSV(qlib_store 复用),CSV 文件名用 qlib 符号。返回写出数。
- `export_csi300_csv(pro, start, end, out_dir)`:tushare index_daily → CSV(符号 SH000300)。
- `build_bin(csv_dir, qlib_dir)`:subprocess 调 qlib dump_bin。
- `init_qlib(qlib_dir)`:`qlib.init(provider_uri=qlib_dir, region=REG_CN)`(幂等,重复调用安全)。

### 3. scores.py — 信号 → qlib score 帧(纯逻辑,可单测)
- `build_score_frame(history, scorer, providers, dates) -> pd.DataFrame`:对 `dates` 中每个交易日,用 providers 算因子 → scorer 出 (code, total) → 累积成 MultiIndex `(datetime, instrument)` 单列 `score` 的 DataFrame(instrument 用 qlib 符号)。
- scorer 这里**不截断 top_n**(回测要全市场打分排序,top_n 截断交给策略的 topk)——给 `DiscoveryScorer` 新增 `score_all(factors)` 方法返回全量 (code,total,raw)(同 `score()` 但不截断);保持原 `score()` 行为不变(回归测试锁定)。
- 全市场逐日跑量大:从 QuoteStore 一次性读区间数据(`get_range`),内存按日切片,不逐日打 DB。

### 4. strategy.py — qlib 策略回测
- `run_strategy_backtest(score_frame, *, topk=8, n_drop=2, benchmark="SH000300", start, end, cost=...) -> dict`:
  - 用 `qlib.contrib.strategy.TopkDropoutStrategy`(signal=score_frame)+ `qlib.backtest.backtest` 程序化 API(非 qrun/MLflow 全家桶)。
  - A股交易成本:买 万3 佣金,卖 万3+千1 印花税(可配)。
  - 用 `qlib.contrib.evaluate.risk_analysis` 出:年化收益、夏普、最大回撤、换手;基准 SH000300 → 超额收益、信息比率。
  - 返回纯 dict(可 JSON 序列化,便于落库/展示)。

### 5. factor.py — 因子 IC 分析
- `factor_report(score_frame, forward_returns) -> dict`:IC、RankIC(均值+IR)、分 N 层(默认5)的分层平均前向收益。
- forward_returns 由 score_frame 的 instrument×date 对齐 QuoteStore 复权收益(T+1 日收益)计算 —— 这段 math 自算(可单测),不依赖 qlib,保证可测;qlib 的 `calc_ic` 可作交叉校验(冒烟)。

### 6. scripts
- `build_qlib_data.py`:export CSV(全市场 + 沪深300)→ build_bin。setsid 后台,打 `QLIB_DUMP_DONE`。
- `run_backtest.py`:init_qlib → build_score_frame(动量信号,可配区间)→ run_strategy_backtest + factor_report → 打印指标。

## 数据流

```
一次性: QuoteStore --export--> CSV(/data/qlib_csv/*.csv, 含 SH000300)
        CSV --dump_bin--> data/qlib_cn (qlib 库)
回测:   init_qlib(qlib_cn)
        QuoteStore 区间数据 --providers+scorer 逐日--> score_frame (datetime×instrument)
        score_frame --> TopkDropoutStrategy + qlib backtest --(benchmark=SH000300)--> 组合/超额指标
        score_frame + QuoteStore 前向复权收益 --> 因子 IC/分层报告
```

## 错误处理
- export/dump:缺数据的 code 跳过并计数;dump_bin 失败抛带 stderr 的异常。
- init_qlib 幂等;qlib 数据目录不存在 → 明确报错提示先跑 build_qlib_data。
- score_frame 某日无数据 → 跳过该日(不产 NaN 行污染回测)。
- tushare index_daily 失败 → 重试;仍失败则中止 build(基准是硬需求)。

## 测试策略(TDD)
**纯单测(synthetic data,不碰 qlib/网络):**
- `symbols`:双向映射、.SH/.SZ/.BJ、非法输入抛错。
- `scores`:假 history+假 provider → score_frame 形状/索引/值正确;空日跳过;instrument 用 qlib 符号。
- `scorer.score_all`:返回全集不截断;**原 `score()` top_n 行为回归不变**。
- `factor`:已知 score+已知前向收益 → 手算 IC/RankIC/分层 与实现一致;NaN/对齐边界。
- `strategy` 指标解析:给定假 qlib report DataFrame → 指标 dict 字段正确(把 risk_analysis 调用与"从其结果取数"解耦,后者可单测)。

**冒烟(小样本,真实 qlib):**
- 取 ~30 只股 + 沪深300 的近 1 年数据 export→dump_bin→init_qlib,跑一次 run_strategy_backtest + factor_report,人工核指标合理(夏普/回撤量级、IC 在 [-1,1])、基准超额可算。

## 范围边界(YAGNI)
- 不做 ML 因子训练(LightGBM/Alpha158 全家桶);因子分析限于对**现有信号分**的 IC/分层。
- 不做参数寻优/walk-forward 调参。
- 不做回测结果落库/前端展示(归入「看板美化」子切片)。
- 不删现有 backtest_dayang/screener 脚本(保留,后续可迁移)。
- 指数只接沪深300 一个基准。

## 构建顺序(垂直切片,各自 TDD)
0 前置数据:symbols + qlib_data(export/dump/init)+ build_qlib_data 脚本(+ 后台跑全量,冒烟用小样本先验证)→ 1 scorer.score_all(回归保护)→ 2 scores 帧组装 → 3 factor IC 报告 → 4 strategy qlib 回测 → 5 run_backtest 脚本 + 小样本冒烟(策略+因子+沪深300基准跑通)。
