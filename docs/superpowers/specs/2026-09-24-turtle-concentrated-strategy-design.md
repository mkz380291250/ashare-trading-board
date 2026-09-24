# 集中持仓盈亏比策略(海龟式)设计

**日期**:2026-09-24
**状态**:用户已批准方案(C+C,3 只,独立模拟账户并行),第一阶段回测待实施

## 背景与动机

现有生产是 qlib 式的 15 只 TopkDropout 周频换仓,用户希望换成"因子挖掘 + 辩论选出好票,进场即定盈亏比,触发即出"的集中持仓策略,并先用历史回测验证能否赚钱。辩论无法在历史上回测(LLM 成本),故回测只验证"因子选票 + 进场时机 + 盈亏比退出"规则,辩论仅作实盘最后过滤。

## 目标

第一阶段:一个独立于 qlib 回测框架的逐日事件驱动回测引擎 + 参数扫描,在创业板动态池 2015 起数据上,比较进场(纯因子 / 因子+突破)× 退出(固定比例 / ATR 海龟)× 时间止损 的组合,用 2015~2021 选参、2022 起验证,给出能否盈利的结论。

第二阶段(回测通过、用户拍板后另立计划):独立模拟账户 `turtle` 并行实盘,夜链开仓候选经辩论否决后开仓,每日盘后止损止盈。

## 非目标

- 不改现有 15 只账户与生产 frozen。
- 不做 ATR 风险头寸(每仓固定 1/3 资金),不做加仓(海龟的分批加仓留后续)。
- 不做行业/相关性约束。

## 数据与宇宙

- 研究库 `data/qlib_cn_full`,宇宙 `cyb_dyn`(含退市),回测起点 2015-01-05,截止日历最后一天。
- 逐日字段:open/high/low/close(复权:全部乘 factor 做后复权价,成交与止损止盈判断都在复权价空间,收益率不受影响)、pre_close 由 Ref(close,1) 得到、涨跌停判定用未复权 open 与 pre_close(创业板 2020-08-24 起 20%,之前 10%;阈值取 0.5% 容差)。
- 因子分:`composite_score` 用 `data/factors/frozen_composite.json`(生产 23 因子)与 `data/factors/wf_cyb_dyn_candidate.json`(≤2021 定因子,严格样本外对照)各跑一遍。
- ATR(20):真实波幅 max(high−low, |high−pre_close|, |low−pre_close|) 的 20 日均值(复权价空间)。
- 20 日新高:close > 过去 20 日(不含当日)最高 high。

## 引擎(`app/backtest/turtle.py`)

纯 pandas/numpy,输入为对齐好的 datetime×instrument 面板(open/high/low/close 复权、raw_open/raw_pre_close、score、atr、hi20),逐日循环:

1. **收盘后生成信号**(用当日数据):候选 = 宇宙内当日有分且未持有的票,按进场规则排序取前 1(每天最多开 1 仓),仅当有空位。
2. **次日开盘执行**:开仓价 = 次日 open(复权);若次日 raw_open ≥ pre_close×(1+涨停幅−0.5%) 视为一字涨停买不到,放弃;若次日无数据(停牌)放弃。每仓资金 = 当前总资产 / slots(3),按 100 股整手向下取整。
3. **退出检查**(对每个持仓,按持仓日从开仓次日起):
   - 固定比例:stop = entry×(1−sl),tp = entry×(1+sl×rr)。
   - ATR:stop = entry − k_stop×ATR(入场日),trailing:持仓期最高 close 回撤 k_trail×ATR 即触发(动态止损 = max(初始 stop, highest − k_trail×ATR))。
   - 触发判定顺序:若 open ≤ stop → 按 open 出;否则 low ≤ stop → 按 stop 出;否则(固定比例)high ≥ tp → open ≥ tp 按 open 否则按 tp 出。同日同时触及止损止盈按止损(保守)。
   - 时间止损:持有天数 ≥ max_hold 且未触发 → 次日开盘出。
   - 跌停(raw_open ≤ pre_close×(1−跌停幅+0.5%))当日不能卖,顺延。
   - 退市/数据终止:按最后一个收盘价出。
4. 成本 0.15%/边,现金无息。记录每笔交易(code, 入场日/价, 出场日/价, 原因, 持有天数, 收益率)与每日净值。

## 进场规则

- `factor`:score 降序第一。
- `breakout`:score 前 30 且当日 close > hi20,多只取 score 最高;无则不开仓。

## 参数网格

- 固定比例:sl ∈ {4,6,8,10}% × rr ∈ {1.5,2,3};ATR:k_stop=2 × k_trail ∈ {2,3};时间止损 max_hold ∈ {20,40,∞}。
- 进场 2 × 退出 (12+2) × 时间 3 = 84 组,每组 2015~今约 2800 天,纯 numpy 循环秒级;两套因子分共 168 组。

## 评估与选参

- 指标:年化、最大回撤、Calmar、夏普、胜率、平均盈亏比(均盈/均亏)、盈利因子(总盈/总亏)、交易数、平均持有天、资金使用率(持仓市值/总资产均值)、相对创业板等权超额。
- 选参:在 2015-01~2021-12 按 Calmar 排序(交易数 < 30 的剔除),取前 5;每组给出 2022-01~今 的样本外指标;并列出最优参数的邻域(sl±2%、rr 相邻档)的 IS/OOS,判断是否孤点。
- 结论标准:样本外 Calmar > 0.5 且盈利因子 > 1.3 且交易数 ≥ 20 视为"可用";否则报告为不可用并给出原因(如触发率、胜率、成本拖累)。
- 产出 `data/reports/turtle_backtest_<date>.{json,md}` 与 `docs/reports/turtle_backtest_<date>.md`(摘要)。

## 脚本

`scripts/run_turtle_backtest.py --universe cyb_dyn --frozen a.json,b.json --start 2015-01-05 --split 2022-01-01 --slots 3 [--grid small]`。

## 测试

`tests/test_backtest_turtle.py`:合成 3 只票小面板:
- 次日开盘成交与涨停跳过;
- 固定止损跳空按开盘价、盘中按止损价;止盈按 tp 价;同日双触按止损;
- ATR 移动止盈随最高价上移;
- 时间止损到期次日开盘出;跌停顺延;
- 退市按最后收盘出;
- 每天最多开 1 仓、槽位上限;
- 指标计算(胜率/盈利因子/Calmar)与手工数值一致。

## 第二阶段(预留,不在本 spec 实施)

独立账户 `turtle`(accounts 表新行),夜链 `turtle` 步:生成开仓候选 → 辩论(现有 DecisionGraph)否决 → 次日开盘挂单(PaperBroker);盘后按选定参数检查止损止盈;UI 加账户切换。
