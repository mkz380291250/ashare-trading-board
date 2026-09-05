# 再平衡换手封顶(n_drop)设计

**日期**:2026-09-05
**状态**:已与用户确认(n_drop=2),待评审

## 背景

系统化 TopkDropout 执行层上线两周(8-24 建仓、8-31 首次轮动),复盘发现**实盘换手远超回测**:第二周卖11换11=单周73%,而回测(`run_composite_backtest`,`n_drop=1` 周频)周换手仅~17%。根因:**部署的再平衡规则与回测的不一致**——回测用 qlib TopkDropout 的 `n_drop` 每周封顶换手,而落地的 `plan_rebalance` 是"凡跌出 topk+buffer 的持仓全卖",无每周换手上限。创业板因子排名周际抖动极大(300910 一周从前15掉到838名),无封顶就会一次性甩卖一大批(8-31 光按排名该卖的就9只)。

换手过高在真实成本账户会显著侵蚀回测的45%(成本随换手线性放大);纸面账户掩盖了这一点,使实盘结果不代表回测。

## 目标

给再平衡加**每周换手封顶 n_drop=2**:每周因排名最多换出2只,把实盘换手拉回回测的低换手轮廓(~13%/周),使实盘行为对齐已验证的45%曲线。

## 非目标

- 不改因子/选股打分、不改宇宙(创业板)、不改前端。
- 不改辩论 SELL 否决(扫雷)逻辑——它抓到过真雷(8-31 的 300682 中报净利−730%),必须保留且**不受封顶限制**。

## 核心设计决策(用户已确认)

1. **n_drop=2**:每周因排名最多换出2只("跌出前20"的持仓里,只卖排名最差的2只;其余掉出榜的这周先留、下周再有机会被剔)。
2. **扫雷不受封顶**:辩论 `action==SELL` 的持仓无条件清仓,不计入 n_drop 额度(安全网优先)。
3. **缓冲带保留**:仍只有 rank>topk+buffer(=20)的持仓才算"掉出榜"、才有资格被 n_drop 剔除;叠加封顶双重降换手。
4. 持仓始终补满到 topk=15(卖几只补几只)。

## 架构与改动

现有链路:`daily_full.step_rebalance` → `execute.rebalance_portfolio` → `rebalance.plan_rebalance`。改动沿这条链串一个 `n_drop` 参数,封顶逻辑落在 `plan_rebalance`,扫雷不受限的行为在 `execute` 中已天然成立(veto 卖出是**额外**加入 `sell_set`,不经 plan 的封顶)。

### 组件级改动

1. **`app/config.py`**:新增 `rebalance_n_drop: int = 2`(注释:每周因排名换出上限;辩论扫雷不受此限)。

2. **`app/portfolio/rebalance.py::plan_rebalance`**:签名加必填关键字 `n_drop`。逻辑:
   - `drop_eligible` = 持仓中 `rank > topk+buffer` 或不在 ranked(退市)的。
   - 按排名**最差优先**排序(不在榜=∞,最先卖),取前 `n_drop` 只为 `sells`(其余掉出榜的本周保留)。
   - `slots` = 补满 topk 的空位数(= len(sells) 封顶后);`buy_candidates` = 未持仓、rank 最高的 `slots+buffer` 个。
   - 返回 `(sorted(sells), buy_candidates)`。

3. **`app/portfolio/execute.py::rebalance_portfolio`**:签名加必填关键字 `n_drop`,透传给 `plan_rebalance(..., n_drop=n_drop)`。**其余不变**——veto 卖出仍在 plan 之后额外并入 `sell_set`(故不受封顶),先卖后买、等权、落 Decision 均不动。

4. **`scripts/daily_full.py::step_rebalance`**:`rebalance_portfolio(...)` 调用加 `n_drop=s.rebalance_n_drop`。

## 数据流

不变,仅 `n_drop` 多穿一层。封顶只作用于"按排名该卖"的集合;delisted 因排名∞排在最前,优先被 n_drop 名额消费(若同周 delisted 超 n_drop,余下下周清,属良性延迟)。

## 错误处理

沿用现有:per-brief 隔离、UsageLimitError 长等重试、下单 fail-soft、非再平衡日早退。无新增失败模式(纯选择逻辑收紧)。

## 测试(TDD)

`plan_rebalance`(纯函数):
- 掉出榜 9 只、n_drop=2 → 只卖排名最差的 2 只,其余 7 只保留;buys 补 2 只。
- 掉出榜 1 只、n_drop=2 → 卖该 1 只(≤ 上限,行为不变)。
- delisted(不在 ranked)2 只 + n_drop=2 → 两只都卖(∞ 排最前)。
- delisted 3 只、n_drop=2 → 本周只卖 2 只(封顶),验证延迟剔除。
- 现有 5 个 plan 测试:更新为传 `n_drop`(高上限如 n_drop=15 保持旧断言不变,证明未回归)。

`rebalance_portfolio`(注入假 graph/broker):
- 持仓中 5 只掉出榜 + n_drop=2:仅 2 只因排名卖出;若另有 1 只被辩论 SELL 否决 → 该只**额外**卖出(总卖3),证明扫雷不受封顶。
- 现有 execute 测试:更新为传 `n_drop`(用不触发封顶的场景,断言不变)。

## 验收标准

1. `rebalance_n_drop=2`;`plan_rebalance` 每周因排名卖出 ≤ n_drop。
2. 辩论 SELL 否决的持仓仍无条件卖出(不占 n_drop 额度)。
3. 持仓补满 15;缓冲带仍生效。
4. 全后端测试绿。
5. scratch 冒烟:构造"多只掉出榜"场景,验证单次再平衡因排名换出 ≤2 只。

## 后续(不在本轮)

- 归因单独跟踪辩论否决层净效果(几周后评估留/关)。
- 若低换手下仍偏离回测,再审视 rebalance_buffer 宽度或调仓频率。
