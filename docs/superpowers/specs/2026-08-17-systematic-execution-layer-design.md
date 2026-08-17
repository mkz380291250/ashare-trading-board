# 执行层换代:系统化 TopkDropout 组合 + 辩论否决 设计

**日期**:2026-08-17
**状态**:已与用户逐点确认,待评审

## 背景

新 h20 低风险因子([[factor-h20-lowrisk]])已上线,组合回测(创业板、TopkDropout、topk=15、周度轮动)扣成本年化 45.1% / 回撤 −21.6% / IR 1.46 / 周换手 2.3 笔,且验证闸确认因子分数正向预测收益(OOS RankIC +0.13、分层单调)。但执行层仍是"逐股辩论 + 0.6 置信度门槛",而置信度已证与收益无关(corr≈0),门槛把每一笔 BUY 拦成 LOW_CONF——一个多月零成交,最近两周更是踏空了一大段涨幅。

用户逐点拍板:① 实盘**系统为主、辩论降级为风险否决**;② 首次实盘**照回测满仓**(前15等权、周度轮动)。本轮把执行层从"辩论定买+置信度门槛"换成"系统化 TopkDropout + 辩论 SELL 否决"。

## 目标

让自动交易真正按已验证的系统化策略开仓:每周一再平衡,持有因子分最高的 15 只创业板股、等权满仓;辩论只在出现明确 SELL(实打实风险)时否决个别标的。纸面账户,无真钱。

## 非目标

- 不做盈利加仓/止盈/移动止损(回测本身无此,YAGNI)。
- 不改因子/选股打分(上一轮已完成)。
- 不改前端(决策/持仓页复用既有接口;状态语义微调见下)。
- 不引入日内/分钟级交易。

## 核心设计决策(用户已确认)

1. **系统为主**:每周再平衡的买卖清单由因子分排名机械决定,不由辩论置信度决定。
2. **辩论=否决层**:只有辩论产出 `action == "SELL"` 才否决——待买标的跳过、取下一名补位;持仓标的清仓。辩论给 HOLD/BUY 或低置信度**不再拦截**。0.6 门槛下线。
3. **满仓等权**:目标持仓 15 只,每只目标市值 = 当前总权益 / 15。
4. **周度轮动**:每周第一个交易日(周一,可配)再平衡;其余交易日不动。辩论从每晚降为每周一次,本地 claude CLI 压力大减。

## 架构与组件

数据流(仅在**再平衡日**执行):
```
选股产物(DiscoveryPick 按 rank) + 当前持仓
   → plan_rebalance(排名, 持仓, topk=15, buffer=5)  → (待卖, 待买候选)
   → 辩论(待买候选 ∪ 持仓)取 verdict           → SELL 者否决
   → 定稿订单(先卖后买,等权 equity/15 定股数)   → PaperBroker 执行
   → 落 Decision 行(供 UI)+ mark-to-market
```

### 新增单元 `app/portfolio/rebalance.py`(纯函数,可独立测试)

- `is_rebalance_day(as_of: date, weekday: int) -> bool`:`as_of.weekday() == weekday`。夜链每晚都进 step,但非再平衡日直接返回不动。
- `plan_rebalance(ranked: list[tuple[str, int]], held: set[str], *, topk: int, buffer: int) -> tuple[list[str], list[str]]`:
  - `ranked` 为 `(code, rank)`(rank 从 1 起)。
  - **待卖** = 持仓中 `rank > topk + buffer` 的、或不在 ranked 中(已退市/掉出宇宙)的 code。
  - **空位数** `slots = topk - (len(held) - len(待卖))`(补满到 topk 需要的新买数)。
  - **待买候选** = 未持仓、rank 最靠前的 code,按 rank 升序返回 `slots + buffer` 个(多给 `buffer` 个作 SELL 否决后的补位后备;`slots<=0` 时返回空)。
  - 纯函数,不触 DB。
- `equal_weight_shares(equity: float, topk: int, price: float, lot: int = 100) -> int`:`floor((equity/topk) / price / lot) * lot`;price≤0 或算出 0 手则返回 0。A股按 100 股整手。

### 改写 `scripts/daily_full.py`:`step_debate` → `step_rebalance`

编排(再平衡日):
1. 读 as_of 的 `DiscoveryPick` 排名;读持仓。
2. `sells, buy_pool = plan_rebalance(...)`(buy_pool 取比空位数多 ~5 个作后备)。
3. 风控停买:`is_risk_off` 为真时**只卖不买**(买清单清空,保留 sells)。
4. 辩论:对 `buy_pool ∪ 持仓` 建 brief 跑 `DecisionGraph`(复用现有 brief_builder,含基本面/财报/研报);取每票 verdict。**辩论池由再平衡直接确定(持仓数 + slots + buffer,约 15~20 只),不经 `select_debate_candidates`,故 `max_debate=8` 不作用于本路径**(周度一次,成本可接受)。
5. 否决与定稿:
   - 持仓 verdict==SELL → 并入 sells。
   - buy_pool 按 rank 顺序取,verdict==SELL 的跳过,取到填满空位为止 → 定为 buys。
6. 执行(**先卖后买**,释放现金):
   - 卖:`PaperBroker.sell(acct, code, latest_close, 全部 shares, as_of)`。
   - 买:先算 `equity = cash + 持仓市值`;每只 `shares = equal_weight_shares(equity, topk, price)`;`PaperBroker.buy(...)`,`InsufficientFunds/Shares` fail-soft(记 reasoning,不崩)。
7. 落 `Decision` 行(每只辩论过的票:action 来自 verdict,status ∈ {`EXECUTED`, `VETOED`, `HELD`, `SOLD`}),供 UI;跑 `build_daily_summary`。
8. 非再平衡日:step 直接打印 `REBALANCE_SKIP 非再平衡日` 返回。

### 退役:`DecisionRunner` 的 min_confidence 门槛

新路径不经 `DecisionRunner` 的买卖逻辑(它按辩论 action+0.6 门槛下单)。`DecisionRunner` 保留供旧 `run_one_decision.py`(UI 手动单票)使用,不删;夜链改走 `step_rebalance`。`Settings.min_confidence` 在夜链路径不再生效(保留字段,注释标注仅手动单票用)。

### 配置新增(`app/config.py`)

```python
rebalance_weekday: int = 0             # 周度再平衡日(0=周一);其余交易日持有不动
rebalance_buffer: int = 5             # TopkDropout 缓冲:持仓跌出 topk+buffer 名才卖(降换手)
# 复用现有 target_positions=15 作 topk;min_confidence 注释补:仅 UI 手动单票用,夜链走系统化
```

## 错误处理

- 单票辩论崩:沿用 per-brief 隔离(`DEBATE_SKIP`),不带崩整轮。
- 限额:沿用 `_retry_on_usage_limit`(UsageLimitError 长等重试)。
- 下单失败(资金/持股不足):fail-soft,记 reasoning,继续其余订单。
- 无当日选股产物:沿用 `step_debate` 现有的 RuntimeError 前置检查。
- 收尾写库撞锁:沿用 run_all 的 3×15s 重试。

## 测试(TDD)

纯函数(不依赖 qlib/DB):
- `is_rebalance_day`:周一 True、其余 False;可配 weekday。
- `plan_rebalance`:① 空仓 → 待买=top15、待卖空;② 持仓全在 top15 → 不动;③ 某持仓 rank=22(>15+5)→ 卖它并补 1 只;④ 持仓 rank=18(在缓冲带内)→ 不卖;⑤ 持仓已退市(不在 ranked)→ 卖;⑥ 待买候选按 rank 升序、数量=空位数(+后备)。
- `equal_weight_shares`:equity=1e6/topk=15/price=10 → 6600 股(整百);price 过高算出 0 手 → 0;price≤0 → 0。

编排(注入假 graph/broker/ranking,不跑真 qlib):
- 再平衡日:空仓 → 买满 15 只等权、先卖后买顺序、落 Decision 行。
- 某 buy 候选辩论 SELL → 跳过取后备补位。
- 某持仓辩论 SELL → 并入卖出。
- 风控停买(is_risk_off True)→ 只卖不买。
- 非再平衡日 → 无订单、无 Decision。
- 全后端回归绿。

## 验收标准

1. 再平衡日空仓起步:PaperBroker 产生 15 笔等权 BUY,持仓表 15 只,现金≈0(满仓)。
2. SELL 否决生效:被否决的买候选不成交、由后备补位;被否决的持仓清仓。
3. 非再平衡日零动作。
4. 0.6 门槛不再拦截夜链买入(LOW_CONF 不再出现在夜链路径)。
5. 全后端测试绿;归因链继续记录每笔实盘 outcome。

## 边界与后续

- **回测乐观性**:45%/−21.6% 的回测窗口与选因子 OOS 窗口重叠、含轻度乐观;辩论 SELL 否决是叠加在已验证系统核心之上的**未独立验证的覆盖层**,归因表会跟踪其净效果(否决对了还是错了)。
- 首版满仓即真实开仓,明确进入交易状态。
- 后续可做:否决层 A/B(开/关对照)、按波动率反比定权(风险平价)、止盈止损、日频再平衡对照。
