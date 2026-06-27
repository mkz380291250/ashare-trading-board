# 量化闭环设计:因子选股 → AI辩论 → 自动执行 → 归因复盘

- 日期:2026-06-27
- 状态:已通过 brainstorming,待 writing-plans
- 架构方案:C(薄编排 + 干净的 attribution / policy 两层)

## 1. 背景与问题

当前链路是一条**开环流水线**,有两个真实缺口:

1. **缺口①(因子没接线)**:`run_discovery.py` 用 `MomentumProvider`(动量百分位)选股,
   而经过优化、RankIC 0.069 的 qlib 复合因子只活在离线回测脚本 `run_composite_backtest.py`
   里,**没有任何线上消费者**。即"用量化因子选入辩论池"这一步实际是断的。
2. **缺口②(无反馈闭环)**:`mark_to_market` 只产出一条权益曲线(赚没赚),但没有决策胜率、
   因子前向 IC、归因复盘——跑出收益却学不到东西,无法判断是因子有效、辩论有效还是运气。

另有一个结构问题:`daily_full.py` 只做"数据更新"(行情→qlib→跟踪表),**不触发**
"选股→辩论→决策",该链路目前靠手动按代码跑。

## 2. 目标

把开环流水线改成**闭环、可无人值守的纸面交易系统**:

```
① 行情更新 → ② 重建qlib数据 → ③ qlib因子打分选股 → ④ AI辩论决策
→ ⑤ 自动纸面执行 + 盯市 → ⑥ 归因(胜率/前向IC/回撤) → ⑦ 策略闸(阈值→自动动作)
```

用户偏好(已确认):纸面虚拟资金,**全自动运行、只看结果**;关键动作走 weixin 推送。

## 3. 范围与非目标

**范围**:一份 spec,分 3 个实施阶段。

- Phase 1:qlib 复合因子**完全替掉** MomentumProvider,冻结因子集、每日只打分
- Phase 2:把"选股→辩论→自动执行→盯市"接进 `daily_full` 每日定时编排
- Phase 3:归因复盘度量层 + 策略闸(三个自动动作)+ 统一护栏

**非目标**:

- 不接实盘资金(仍 PaperBroker);护栏按"可审计/可回滚/可解释"做,不做实盘级熔断/额度
- 不重做因子挖掘算法本身(复用现有 `run_factor_mining` / `composite_score`)
- 前端展示为可选增量,不阻塞后端闭环

## 4. 总体架构(方案 C)

薄编排负责"按顺序调用",业务逻辑全在可独立测试的包里。

**模块布局**

- `app/discovery/qlib_provider.py` ★新 —— 加载冻结因子产物,对全市场打分
  (复用 `composite_score` / `cs_zscore` / `FACTOR_LIBRARY`)
- `app/factors/frozen.py` ★新 —— 冻结产物读写(因子集+符号+权重+元数据)
- `app/attribution/` ★新包 —— `outcomes.py` / `forward_ic.py` / `equity.py`
- `app/policy/` ★新包 —— `rules.py` / `actions.py` / `guardrails.py`
- `scripts/daily_full.py` 改 —— run_all 链尾追加 选股/辩论/执行/盯市/归因/策略闸
- 现有 `daily_scheduler_daemon.sh` + APScheduler 调 `run_all()`,收盘后 16:30 触发

**闭环数据流**

```
daily_full.run_all():
 ① step_quotes      (现有 daily_update_quotes)
 ② step_qlib        (现有 build_qlib_data)
 ③ step_select  ★   QlibCompositeProvider → DiscoveryPick(全量排序)
 ④ step_debate  ★   有界迭代:对 TopN 跑 DecisionGraph → Decision
 ⑤ step_execute ★   置信度达标的 BUY/SELL 自动纸面下单
    step_mark   ★   mark_to_market → EquitySnapshot
 ⑥ step_attribution ★  decision_outcomes / factor_ic_daily / 回撤
 ⑦ step_policy  ★   rules → actions(过 guardrails)
 ⑧ 收盘 weixin 日报
```

## 5. Phase 1 — qlib 因子接线

### 5.1 冻结产物 `data/factors/frozen_composite.json`

由 `run_factor_mining` 的一个 `freeze` 步骤(或 policy 自动重挖)产出:

```json
{
  "as_of": "2026-06-25",
  "factors": ["vstd20", "corr_pv10", "..."],
  "signs":   {"vstd20": -1, "rev3": 1},
  "weights": {"vstd20": 0.0556},
  "universe": "investable",
  "horizon": 5,
  "source_report": "factor_mining_2026-06-25",
  "metrics_at_freeze": {"rank_ic_mean": 0.0695, "rank_ic_ir": 0.58}
}
```

关键约定:**只存因子名,不存表达式**。表达式始终从代码里的 `FACTOR_LIBRARY` 取,
避免产物与因子库不一致。`weights` 现为等权,保留字段以备扩展。

### 5.2 `QlibCompositeProvider`(每日打分)

不走 `snapshot`,直接读 qlib:

1. 加载 `frozen_composite.json`,取 `factors` + `signs`
2. `D.features(investable_insts, [FACTOR_LIBRARY[n] for n in factors], 最近~60交易日)`
   —— 短窗仅为算当日截面 z-score
3. `cs_zscore` 各因子 → `composite_score(panel, signs)` → 取**最新交易日**那条截面
4. 排序 → 写 `DiscoveryPick(as_of, code, rank, score, factors=各因子分快照)`,**全量落库**
   (不止 TopN,因有界迭代需往下取)

### 5.3 完全替掉动量

`run_discovery.py` 增加 `--source qlib|momentum`,**默认 qlib**。qlib 路径让
`QlibCompositeProvider` 直接产出排序并写 `DiscoveryPick`,**不经 `DiscoveryScorer` 的百分位
机制**(复合分已是最终排序信号,再过百分位反而失真)。`--with-research` 研报信号保留为
**可选叠加**,不污染主因子排序。

### 5.4 验收

跑一天 `run_discovery --source qlib`,产出的排序与当日 `composite_score` 一致;
与离线回测同日截面对拍不漂移。

## 6. Phase 2 — 每日定时编排

### 6.1 有界迭代选股辩论(关键逻辑)

不强迫交易:空仓是合法仓位。`step_debate` 逻辑:

- `空位 = 目标仓位(默认15) − 当前持仓数`
- 从 `DiscoveryPick` 排名往下,每批 8 只送 `DecisionGraph` 辩论,累计 BUY 填空位
- **停止条件(任一即停)**:填满空位 / 候选复合分跌出全市场前 30% / 排名取尽
- 绝不为了"不空仓"而强买弱票

参数旋钮:目标仓位 `target_positions=15`、质量门槛 `quality_pctl=0.30`、批大小 8、
单日辩论上限 `max_debate=32`(4 批,触顶停+告警,防烧 LLM)。

### 6.2 自动执行

`step_execute`:辩论结论 BUY/SELL 且 `confidence ≥ buy_threshold(默认0.6)` 即**自动纸面下单**
(PaperBroker)。决策全量落库可复盘。**无人工批准关口**(纸面虚拟资金,用户只看结果)。

### 6.3 编排原则

1. **失败隔离**:沿用 `run_all` 逐步 try/except,单步失败不阻断后续;但有数据依赖的步
   (debate 依赖 select 产物)缺料则跳过+告警,**不拿旧数据硬跑**。
2. **幂等**:同一交易日重复跑不重复下单。`step_select` 以 `as_of` 覆盖 DiscoveryPick;
   `step_debate`/`step_execute` 以 `(as_of, code)` 去重,已存在的当日决策不重复辩论(省 LLM)。

### 6.4 调度

`daily_scheduler_daemon.sh` + APScheduler 收盘后 16:30 触发 `run_all()`。辩论单独计时。

### 6.5 验收

手动 `python scripts/daily_full.py` 一次,链路从行情跑到 EquitySnapshot;
重复跑不产生重复决策/持仓。

## 7. Phase 3 — 归因复盘 + 策略闸 + 护栏

### 7.1 attribution 包(度量层)

- `outcomes.py` → 表 `decision_outcomes`:复刻 `WatchPoolEntry` 的 ret_t1/t3/t5/t10,
  对每条 BUY/SELL 决策回填后向收益,算**决策胜率**(BUY 后涨=命中),可按置信度/角色分组
- `forward_ic.py` → 表 `factor_ic_daily`:每日复合分截面 vs 之后实现的 5 日收益 → 当日 IC/RankIC 时序
- `equity.py`:从 `EquitySnapshot` 算滚动回撤、对沪深300超额(纯计算+缓存,无新表)

### 7.2 policy 包(阈值→动作)

`rules.py` 读 attribution 指标判定,`actions.py` 执行,全部经 `guardrails.py`。

**三个自动动作**(默认阈值,实测后再调):

1. **因子衰减→自动重挖**:`factor_ic_daily` 滚动 20 日 RankIC 连续 5 日 < 0.02
   → 自动跑 `run_factor_mining` 产出新冻结产物。纸面默认**自动换上线 + 留旧产物 + weixin 通知 +
   可一键回滚**;`confirm` 开关可改成"只产候选、等确认再换"。
2. **风控→自动减/停买**:权益回撤 > 20% 或滚动决策胜率 < 40% → 置 `risk_off` 标志,
   `step_debate` 读到即当日停买(可选按比例减仓)。condition 恢复后自动解除;每次切换推 weixin。
3. **持仓弱因子→自动标卖**:每日给持仓用复合因子打分,某持仓跌出全市场前 50% 连续 3 日
   → 生成 SELL 候选进 `step_debate`,辩论确认 SELL 即自动执行。

### 7.3 guardrails.py(统一护栏入口)

每个自动动作执行前必过:

1. 写 `policy_actions` 审计表(动作类型/触发指标/时间/前后状态/回滚句柄)
2. 查 `confirm` 开关:自动执行 or 挂起待确认
3. 关键动作(换因子产物、停买、卖出)推 weixin
4. 提供 `rollback(action_id)`

将来接实盘只需把默认开关从"自动"翻成"确认"。

### 7.4 验收

构造历史并注入"IC 连续走低 / 回撤超 20% / 某持仓因子转弱",验证三个动作分别触发、
审计落库、weixin 发出、可回滚;胜率/前向 IC 时序可查。

## 8. 数据模型变更

新增表:

- `decision_outcomes` — 决策后向收益与命中(ret_t1/t3/t5/t10 + hit 标记 + 关联 decision_id)
- `factor_ic_daily` — 每日 IC/RankIC 时序(as_of, ic, rank_ic, n)
- `policy_actions` — 自动动作审计(类型/触发指标/前后状态/rollback 句柄/weixin 状态/confirm)

复用现有:`DiscoveryPick`、`Decision`、`EquitySnapshot`、`WatchPoolEntry`(模式参考)。

冻结产物为文件:`data/factors/frozen_composite.json`(+ 历史归档目录留旧版供回滚)。

## 9. 测试策略(pytest)

- **单元**:`QlibCompositeProvider` 排序;`policy/rules` 阈值判定;`guardrails` 审计与回滚;
  有界迭代三种停止条件
- **集成**:`daily_full.run_all()` 在小型 fixture DB 端到端,断言 DiscoveryPick→Decision→持仓→
  EquitySnapshot;重复跑幂等
- **归因正确性**:构造已知后向收益,断言胜率 / 前向 IC 计算值
- **对拍**:Phase 1 与离线回测同日截面不漂移

## 10. 容错与可观测

- 每步 try/except 不阻断;有数据依赖的步缺料则跳过+告警
- LLM 辩论单日批次上限 32,触顶停+告警
- policy 任一动作异常只记录+告警,绝不拖垮当日链路
- 收盘 weixin 日报:当日买/卖/持、权益与回撤、复合因子前向 IC、是否触发自动动作
- weixin 渠道纪律:内容消息放回合末尾、不夹在工具洪流里、多条间隔 ≥10 秒、不用 markdown 表格

## 11. 实施阶段顺序

1. **Phase 1** 因子接线(独立可验收,先让线上用上优化好的因子)
2. **Phase 2** 每日定时编排 + 自动执行(打通无人值守主链)
3. **Phase 3** 归因复盘 + 策略闸 + 护栏(闭环最后一环)

每阶段独立验收后再进下一阶段。
