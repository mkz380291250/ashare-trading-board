# 因子换代:短周期价量反转 → 长周期(h20)低风险异象 设计

**日期**:2026-08-06
**状态**:已探索验证,待评审

## 背景与动机

生产因子一个多月零成交,且诊断出根因不在门槛而在信号本身:

- 辩论置信度、因子分数都与后续收益近乎无关(置信度 corr≈0;因子分与5日收益 corr=**−0.35**,即因子最看好的票 5 天后跌得最惨)。
- 当前冻结组合是 h5(5日)价量反转型,建在最不稳的短周期上,信号周期与"多日持有"错配。

### 探索结论(创业板宇宙,2026-08-06,IS 2022-01..2025-01 / OOS 2025-01..今)

按 9 个家族 × 3 个持有周期(h5/h10/h20)铺开单因子 OOS RankIC:

- **动量趋势家族全周期负相关**(h5 −0.043 → h20 −0.054,13 个里仅 1 个正向):创业板追涨在任何周期都亏,"换趋势型"方向被数据否决。
- **低风险异象家族正向/稳健,且随周期变长增强**:非流动性 Amihud +0.062→**+0.096@h20**(2/2 稳健全正向);低波动 −0.08@h20(4/4 稳健);低换手 −0.05@h20(9/10 稳健);反彩票 maxret(4/4 稳健)。经济含义一致:买清淡/低波动/低流动/不妖的票。
- 反转(rev)方向对但太弱,单用过不了稳健线,只能当配角。

**组合验证(决定性)**:用 h20 低风险家族因子(vol20/vol60/wvma20/turn20/turn_std20/vstd20/amihud20/amihud_amt20/maxret20/corr_pv20,符号修正后按日截面 z-score 等权):

- 组合分数 vs 20 日收益 **OOS RankIC = +0.126,IR = 0.72**(远超 0.3 稳健线)
- IS +0.134 vs OOS +0.126 一致,非过拟合
- 分层收益**单调递增**:最低分组 20 日 +0.68% → 最高分组 +2.42%,高低差 +1.74%

即:把当前 −0.35 的负相关**掰正为 +0.126 且单调**。这是本次换代的核心依据。

## 目标

把生产因子从 h5 价量反转换成 **h20 低风险异象**,宇宙仍为创业板(cyb),并让换代后的复合因子通过"组合分数正向预测 h20 收益"的验证闸。

## 非目标(明确排除)

- **不改交易执行**:0.6 置信度门槛、仓位、退出逻辑本轮全部不动(用户已定"先不碰交易")。
- **因此本轮改动本身不会产生买入**:LOW_CONF 门槛仍在,持仓仍会为空。本轮只把"信号修对";执行/门槛/退出是**紧接着的下一轮**(信号对齐后再谈交易才有意义)。
- 不引入 LightGBM 学习权重(留作后续)。
- 不新增归因 t20 窗口(可选后续;当前 t1/t3/t5/t10 不足以完整评估 h20 策略,但不阻塞本轮)。

## 架构与改动

信号链路:`config.discovery_horizon` → 挖掘(run_factor_mining)→ 冻结(freeze_factors)→ 打分选股(qlib_provider.score_panel)→ 辩论话术(daily_full/_reversal_thesis + agents.py)→ 归因。

单一事实源:**新增 `Settings.discovery_horizon`**,挖掘与冻结脚本的 horizon 默认都从它取(完全比照 `discovery_universe` 的现成模式,防止 `run_remine` 静默把周期切回 5——这正是 universe 曾踩过的坑)。

### 组件级改动

1. **`app/config.py`**:新增 `discovery_horizon: int = 20`(注释说明:生产因子持有/预测周期,挖掘/冻结默认跟随)。更新 `buy_trend_window` 注释里"当前 frozen 因子是短周期反转型(专挑超跌)"这句(已不成立)。

2. **`scripts/run_factor_mining.py`**:`--horizon` 默认从 `None` 解析为 `settings.discovery_horizon`(现为硬编码 `default=5`),比照现有 `--universe` 的写法。

3. **`scripts/freeze_factors.py`**:`freeze(..., horizon=None)` → 缺省用 `settings.discovery_horizon`(现为硬编码 `horizon=5`);CLI 增 `--horizon`。

4. **新增 `scripts/validate_frozen_alignment.py`**(验证闸):加载当前 `frozen_composite.json`,在其 `horizon`、`universe` 上,**直接复用生产打分函数 `app.quant.factor_compose.composite_score(panel, frozen.signs)`**(即"按日截面 z-score × 符号、跨因子等权平均"——已核对与生产选股 `score_panel` 为同一函数,保证验证的分数就是实际选股用的分数),计算复合分数对 h 日远期收益的 OOS RankIC 与分层收益。**通过条件**:OOS RankIC ≥ +0.05 且最高分层收益 ≥ 最低分层收益。不通过则退出码非 0 并打印原因——用于换代后把关,防再次上线一个分数与收益反向的组合。

5. **话术一致性 `scripts/daily_full.py` 与 `app/decision/agents.py`**:`_reversal_thesis` 改名 `_lowrisk_thesis`(或中性 `_strategy_thesis`),文案从"超跌反弹、下跌是入选理由、评估反弹胜算"改为低风险异象口径:"本股因低波动/低换手/清淡流动/非妖股特征入选,请评估其作为稳健低波标的的持有价值(而非动量突破或超跌反弹)"。agents.py 中量价/多头/交易员/风控里 4 处"若选股逻辑为超跌反弹…"的条件分支同步改为低风险口径。

### 数据/产物操作(非代码,执行期)

- 换代前**备份**当前 `data/factors/frozen_composite.json` 到 `data/factors/archive/frozen_composite_2026-08-06_h5reversal.json`(比照既有 archive 惯例)。
- 用 `discovery_horizon=20` 重挖创业板 → `data/reports/factor_mining_<date>_h20.json`。
- 用该报告重新冻结 → 新 `frozen_composite.json`(horizon=20)。
- 跑验证闸 `validate_frozen_alignment.py`,必须通过。
- (data/ 为 gitignored;容器重建恢复方式不变,见 [[ashare-deploy-serving]] 惯例。)

## 数据流

选股:`run_qlib_discovery` 读 `frozen.factors/signs` → `score_panel(panel, frozen.signs)` 出复合分 → 排名入 `DiscoveryPick`。此路径**无需改代码**——它已用 `frozen.signs` 打分,换 frozen 产物即换策略。horizon 仅影响挖掘/冻结/验证与话术,不影响打分函数本身。

## 错误处理

- 验证闸不通过 → 不上线新 frozen,保留备份可一键回滚。
- horizon 单一源:任何脚本忘传 horizon 都回落到 `discovery_horizon`,不会静默用 5。
- 重挖/冻结沿用既有 fail-soft 与 report 定位逻辑(`--report`/`--universe`/`--horizon` 显式可控,防选错报告文件)。

## 测试(TDD)

- `test_config`:`discovery_horizon` 默认 20。
- `test_freeze_factors`:`freeze` 未传 horizon 时用 `settings.discovery_horizon`;传 `--horizon` 时覆盖;写入 frozen 的 `horizon` 字段正确。
- `test_run_factor_mining`:`--horizon` 缺省解析为 settings 值(参数解析层,不实跑 qlib)。
- `test_validate_frozen_alignment`:构造一个"分数正向预测收益"的假面板→通过;构造"负向"假面板→失败退出。用注入的 `load_features_fn`/假数据,不依赖真 qlib。
- `test_daily_full` / `test_agents`:话术函数返回低风险口径文案(断言关键词从"超跌反弹"变为"低波动/低换手/稳健");agents.py 分支文案更新后现有断言同步。

## 验收标准

1. 新 `frozen_composite.json`:`horizon=20`、`universe=cyb`、因子集为 h20 稳健(符号修正)。
2. `validate_frozen_alignment.py` 对新 frozen 通过(OOS RankIC ≥ +0.05 且分层单调方向正确);实测目标 ~+0.126。
3. 全后端测试绿。
4. 辩论话术与选股逻辑口径一致(不再出现"超跌反弹")。
5. 旧 h5 组合已备份、可回滚。

## 后续(不在本轮)

- 执行层:重估 0.6 门槛(已知置信度是噪音)、补短线/持有期退出、仓位——本轮信号对齐后启动。
- 归因新增 t20 窗口以匹配 h20 评估。
- LightGBM 学习权重(48 因子)。
