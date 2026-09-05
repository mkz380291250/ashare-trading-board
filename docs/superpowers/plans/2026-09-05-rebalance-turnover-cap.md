# 再平衡换手封顶(n_drop=2)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给再平衡加每周换手封顶——因排名最多换出 n_drop=2 只,辩论 SELL 否决(扫雷)不受此限,把实盘换手拉回回测低换手轮廓。

**Architecture:** 沿 `daily_full.step_rebalance → execute.rebalance_portfolio → rebalance.plan_rebalance` 串一个 `n_drop` 参数;封顶逻辑落在 `plan_rebalance`(在"跌出 topk+buffer"的持仓里按排名最差取前 n_drop 卖出);扫雷"不受限"在 `execute` 中天然成立(veto 卖出是额外并入 `sell_set`,不经 plan 封顶)。

**Tech Stack:** Python 3.11、pytest。纸面账户,无真钱。

## Global Constraints

- `rebalance_n_drop = 2`:每周因排名换出上限。
- 辩论 `action == "SELL"` 的持仓无条件清仓,不计入 n_drop 额度。
- 缓冲带保留:仅 `rank > topk + buffer`(topk=15、buffer=5,即 rank>20)的持仓才有资格被 n_drop 剔除。
- 持仓补满到 topk=15。
- delisted(不在 ranked)持仓排名视作 ∞、最先被 n_drop 名额消费。
- TDD;后端测试命令:`cd backend && .venv/bin/python -m pytest <file> -q`。

---

### Task 1: config + `plan_rebalance` 换手封顶

**Files:**
- Modify: `backend/app/config.py`(新增 `rebalance_n_drop`)
- Modify: `backend/app/portfolio/rebalance.py`(`plan_rebalance` 加 `n_drop` 封顶)
- Test: `backend/tests/test_config_phase2.py`、`backend/tests/test_portfolio_rebalance.py`

**Interfaces:**
- Produces:
  - `Settings.rebalance_n_drop: int = 2`
  - `plan_rebalance(ranked, held, *, topk: int, buffer: int, n_drop: int) -> tuple[list[str], list[str]]`(签名新增必填 `n_drop`;因排名卖出 ≤ n_drop)

- [ ] **Step 1: 写失败测试(config)**

在 `backend/tests/test_config_phase2.py` 末尾追加:

```python
def test_rebalance_n_drop_default_2():
    from app.config import Settings
    assert Settings().rebalance_n_drop == 2
```

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config_phase2.py::test_rebalance_n_drop_default_2 -q`
Expected: FAIL(`AttributeError: ... rebalance_n_drop`)

- [ ] **Step 3: 实现 config**

在 `backend/app/config.py` 的 `Settings` 中,`rebalance_buffer` 之后加:

```python
    rebalance_n_drop: int = 2             # 每周因排名换出上限(封顶换手);辩论扫雷不受此限
```

- [ ] **Step 4: 写失败测试(plan_rebalance 封顶)**

在 `backend/tests/test_portfolio_rebalance.py` 末尾追加(`_ranked` 已在该文件定义,codes `3000{i:02d}.SZ`、rank=i+1):

```python
def test_plan_caps_rank_sells_at_n_drop():
    # 9 只掉出榜(rank 22..30 > 20),n_drop=2 → 只卖排名最差的 2 只(rank30、29)
    held = {f"3000{i:02d}.SZ" for i in range(6)} | {f"3000{i:02d}.SZ" for i in range(21, 30)}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5, n_drop=2)
    assert sells == sorted(["300029.SZ", "300028.SZ"])   # rank30、rank29 最差
    assert len(buys) >= 2                                 # 至少能补回卖出的空位


def test_plan_delisted_capped_by_n_drop():
    # 3 只退市(不在 ranked),n_drop=2 → 本周只卖 2 只
    held = {"999997.SZ", "999998.SZ", "999999.SZ"}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5, n_drop=2)
    assert len(sells) == 2


def test_plan_n_drop_not_exceeded_when_fewer_drops():
    # 只 1 只掉出榜(rank26>20),n_drop=2 → 卖该 1 只(不足上限,行为不变)
    held = {f"3000{i:02d}.SZ" for i in range(14)} | {"300025.SZ"}
    sells, buys = plan_rebalance(_ranked(30), held, topk=15, buffer=5, n_drop=2)
    assert sells == ["300025.SZ"]
```

同时把该文件**现有 5 处** `plan_rebalance(...)` 调用(第 17/25/33/41/47 行,均为 `topk=15, buffer=5`)各加一个 `, n_drop=15`(高上限=不封顶,保持旧断言不变以证明未回归)。例如:
`sells, buys = plan_rebalance(_ranked(30), set(), topk=15, buffer=5, n_drop=15)`

- [ ] **Step 5: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_rebalance.py -q`
Expected: FAIL(现有调用因缺 `n_drop` 参数报 `TypeError`;新用例断言失败)

- [ ] **Step 6: 实现 plan_rebalance**

把 `backend/app/portfolio/rebalance.py` 的 `plan_rebalance` 整体替换为:

```python
def plan_rebalance(ranked, held, *, topk: int, buffer: int, n_drop: int):
    """ranked: list[(code, rank)](rank 从 1);held: 持仓 code 集合。
    返回 (sells, buy_candidates):
      sells = 持仓中 rank>topk+buffer 或已不在 ranked(退市)的,按排名最差优先
              取前 n_drop 只(每周因排名换出封顶);
      buy_candidates = 未持仓、rank 最靠前的 slots+buffer 个(slots=补满 topk 的空位)。"""
    held = set(held)
    rank_of = {c: r for c, r in ranked}
    ranked_codes = [c for c, _ in sorted(ranked, key=lambda x: x[1])]
    BIG = float("inf")
    drop_eligible = [c for c in held
                     if c not in rank_of or rank_of[c] > topk + buffer]
    # 最差排名优先(退市=∞ 最先卖);每周因排名最多卖 n_drop 只
    drop_eligible.sort(key=lambda c: rank_of.get(c, BIG), reverse=True)
    sells = sorted(drop_eligible[: max(0, n_drop)])
    remaining = len(held) - len(sells)
    slots = max(0, topk - remaining)
    if slots <= 0:
        return sells, []
    buy_candidates = [c for c in ranked_codes if c not in held][: slots + buffer]
    return sells, buy_candidates
```

- [ ] **Step 7: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_rebalance.py tests/test_config_phase2.py -q`
Expected: PASS(全部)

- [ ] **Step 8: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/app/config.py backend/app/portfolio/rebalance.py backend/tests/test_config_phase2.py backend/tests/test_portfolio_rebalance.py
git commit -m "feat: plan_rebalance 加 n_drop 换手封顶(因排名每周最多换n_drop只)"
```

---

### Task 2: 串 `n_drop` 过 execute 与 daily_full

**Files:**
- Modify: `backend/app/portfolio/execute.py`(`rebalance_portfolio` 加 `n_drop`,透传)
- Modify: `backend/scripts/daily_full.py`(两处 `plan_rebalance`/`rebalance_portfolio` 调用传 `n_drop`)
- Test: `backend/tests/test_portfolio_execute.py`

**Interfaces:**
- Consumes: `plan_rebalance(..., n_drop=)`(Task 1)。
- Produces: `rebalance_portfolio(session, as_of, ranking, holdings, *, graph, broker, brief_builder, price_of, equity_of, topk, buffer, n_drop, risk_off=False, account_id=1) -> dict`。

- [ ] **Step 1: 写失败测试(扫雷不受封顶)**

在 `backend/tests/test_portfolio_execute.py` 末尾追加(`_Graph`/`_brief_builder`/`_ranked`/`_seed_account`/`_equity_of` 均已在该文件定义):

```python
def test_veto_sell_bypasses_n_drop_cap(session):
    _seed_account(session, cash=700_000.0)
    broker = PaperBroker(session)
    # 5 只掉出榜(rank 22..26 >20)+ 1 只 rank1 但辩论 SELL
    dropped = [f"3000{i:02d}.SZ" for i in range(21, 26)]
    held_codes = dropped + ["300000.SZ"]
    for c in held_codes:
        broker.buy(1, c, 10.0, 6600, date(2026, 8, 10))
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(held_codes),
        graph=_Graph({"300000.SZ": "SELL"}), broker=broker,
        brief_builder=_brief_builder, price_of=lambda c: 10.0,
        equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5, n_drop=2)
    # 掉出榜5只里因排名最多卖2只 + 辩论SELL的300000额外卖 = 共3只
    assert len(res["sold"]) == 3
    assert "300000.SZ" in res["sold"]                    # 扫雷不受 n_drop 封顶
```

同时把该文件**现有 5 处** `rebalance_portfolio(...)` 调用(第 42/58/72/85/97 行,末尾为 `topk=15, buffer=5)` 或 `topk=15, buffer=5, risk_off=True)`)各加一个 `n_drop=15`(高上限=不封顶,保持旧断言)。例如第 85 行 `topk=15, buffer=5, risk_off=True)` → `topk=15, buffer=5, n_drop=15, risk_off=True)`;其余 `topk=15, buffer=5)` → `topk=15, buffer=5, n_drop=15)`。

- [ ] **Step 2: 跑,确认失败**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_execute.py -q`
Expected: FAIL(现有调用缺 `n_drop` 报 `TypeError`;新用例因签名未更新失败)

- [ ] **Step 3: 实现 execute 改动**

在 `backend/app/portfolio/execute.py`,`rebalance_portfolio` 签名加 `n_drop`(放在 `buffer` 之后):

```python
def rebalance_portfolio(session, as_of, ranking, holdings, *, graph, broker,
                        brief_builder, price_of, equity_of, topk, buffer, n_drop,
                        risk_off=False, account_id=1) -> dict:
```

并把函数体内 `plan_rebalance(ranking, holdings, topk=topk, buffer=buffer)` 一行改为:

```python
    sells, buy_pool = plan_rebalance(ranking, holdings, topk=topk,
                                     buffer=buffer, n_drop=n_drop)
```

其余不动(veto 卖出仍在其后额外并入 `sell_set`,不受封顶)。

- [ ] **Step 4: 实现 daily_full 改动**

在 `backend/scripts/daily_full.py`:

研报预算的 `plan_rebalance` 预调用(约 163-164 行)加 `n_drop`:
```python
    _sells, _buy_pool = plan_rebalance(ranking, held, topk=s.target_positions,
                                       buffer=s.rebalance_buffer, n_drop=s.rebalance_n_drop)
```

`rebalance_portfolio` 调用(约 210-216 行)在 `buffer=s.rebalance_buffer,` 之后加 `n_drop=s.rebalance_n_drop,`:
```python
        return rebalance_portfolio(
            session, as_of, ranking, held,
            graph=DecisionGraph(_llm(s), rounds=s.debate_rounds),
            broker=PaperBroker(session), brief_builder=brief_builder,
            price_of=lambda c: latest_close(store, c, as_of),
            equity_of=_equity_of, topk=s.target_positions,
            buffer=s.rebalance_buffer, n_drop=s.rebalance_n_drop,
            risk_off=off, account_id=1)
```

- [ ] **Step 5: 跑,确认通过**

Run: `cd backend && .venv/bin/python -m pytest tests/test_portfolio_execute.py -q && .venv/bin/python -c "import scripts.daily_full"`
Expected: PASS(全部);import 无错。

- [ ] **Step 6: 提交**

```bash
cd /root/.openclaw/workspace/ashare-trading-board
git add backend/app/portfolio/execute.py backend/scripts/daily_full.py backend/tests/test_portfolio_execute.py
git commit -m "feat: 串 n_drop 过 rebalance_portfolio 与夜链;扫雷不受封顶(测试守护)"
```

---

### Task 3:(运维,由控制者执行)全量回归 + 换手封顶冒烟

> 不写代码。验证:全后端绿;端到端下,单次再平衡因排名换出 ≤ n_drop。不动实盘账户(scratch account 99)。

- [ ] **Step 1: 全后端回归绿**

```bash
cd /root/.openclaw/workspace/ashare-trading-board/backend && .venv/bin/python -m pytest tests/ -q
```
Expected: all passed。

- [ ] **Step 2: scratch 换手封顶冒烟**

写一次性脚本:account_id=99、假 as_of=`date(2099,1,1)` 隔离决策、真实最新 `DiscoveryPick` 排名;先给 99 号建 15 只持仓,其中**故意放 5 只当前排名 >20 的票**(从排名尾部取),`graph` 全 HOLD 桩,调 `rebalance_portfolio(..., topk=15, buffer=5, n_drop=2)`;断言 `len(res["sold"]) == 2`(因排名只换2只)。跑完删除 account 99 及其持仓/成交、并删除 as_of=2099-01-01 的 Decision 行。
(注:价格用真实最新交易日 `latest_close(store, code, <最新交易日>)`,不要用 2099——2099 取价为 None;决策隔离才用 2099 as_of。若同时需要真实价与隔离决策,给 rebalance_portfolio 传真实交易日 as_of 并在跑前快照、跑后还原该日 Decision,如上一轮冒烟做法。)

- [ ] **Step 3: 确认生效时点**

`rebalance_n_drop=2` 下个周一夜跑(北京22:00)自动生效,无需重启守护进程。首个受益轮动即为下次再平衡日。

---

## Self-Review

**Spec 覆盖**:
- config `rebalance_n_drop=2` → Task 1 ✓
- plan_rebalance 因排名卖出 ≤ n_drop、最差优先、退市∞最先 → Task 1(实现+3新测试)✓
- 缓冲带保留(rank>topk+buffer 才有资格) → Task 1(逻辑保留)✓
- 扫雷不受封顶 → Task 2(execute veto 额外并入,test_veto_sell_bypasses_n_drop_cap 守护)✓
- 补满 topk → Task 1(slots=topk-remaining 不变)✓
- 串一路参数 → Task 2(execute + daily_full 两处 plan 调用 + rebalance 调用)✓
- 全量回归 + 冒烟 → Task 3 ✓

**占位符扫描**:无 TBD/TODO;代码步均给完整代码;Task 3 运维步给了明确命令与断言。

**类型一致性**:`plan_rebalance(..., n_drop: int)` 在 Task 1 定义、Task 2 的 execute 与 daily_full 两处调用一致;`rebalance_portfolio(..., n_drop, ...)` 参数位置(buffer 后、risk_off 前)在 execute 定义与 daily_full/测试调用一致;`Settings.rebalance_n_drop` 引用一致;`_ranked`/`_Graph` 等测试夹具沿用现有文件定义。

**范围**:单一改动(换手封顶),一个计划。
