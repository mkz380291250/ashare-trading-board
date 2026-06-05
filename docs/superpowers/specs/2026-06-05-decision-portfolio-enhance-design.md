# 决策与持仓增强设计:按需辩论 + 自动批准 + 持仓盈亏 + 股票名称

日期:2026-06-05
分支:基于 `feat/frontend-redesign`(最新 UI)

## 背景与需求(用户 2026-06-05)

1. 决策界面可**自行输入股票代号**,提交后让 AI 多智能体**异步辩论**。
2. 决策详情页可**手动执行买入/卖出**。
3. 决策**默认全部自动批准**(生成即执行,不用手点)。
4. 首页看板中买入的股票需显示**买入时间、成本、持仓盈亏**。
5. **所有股票都要带股票名称**(不只是代码)。

## 现状关键事实

- `Position` 表只有 code/shares/cost(均价),**无买入时间**;`Trade` 表有 `traded_at`(date)→ 买入时间 = 该 code 最早 BUY 的 traded_at。
- **全库无股票名表**(仅 Account.name、tracklist.name)。
- `PaperBroker.buy(account_id, code, price, shares, as_of)` / `sell(...)` 已有;`POST /api/trade` 已有。
- `DecisionRunner.run(as_of, briefs)` 落 `Decision`,当前 `status="PENDING"`。
- `QuoteStore.get_bars(code, start, end)` 可取最新收盘;`trading_dates(end, limit)`。
- 决策一只本地 Claude 辩论约 4 分钟(慢)。

## 用户已确认的决策

- 自动批准:决策生成即 `APPROVED`,并**用最新收盘价**自动 PaperBroker 下单(BUY/SELL 且 shares>0;HOLD 不动)。
- 按需辩论:**异步**(提交 → 后台跑 → 完成出现在列表),不卡 UI。
- 手动买卖:决策详情页加**手动买/卖小面板**(股数+价)。
- P&L 现价:用**历史库最新收盘价**(日线收盘制,非实时)。

## 分块设计(一份 spec,计划分阶段;块①是其余块的基础)

### 块① 股票名称(基础设施)

- 新表 `StockName`(`stock_names`):`code`(PK,String16)、`name`(String32)。
- 新脚本 `scripts/sync_stock_names.py`:用 tushare `stock_basic`(字段 ts_code,name)一次拉全市场,幂等 upsert 落库。可重跑刷新。
- 新模块 `app/data/names.py`:`NameLookup(session)`,方法 `get(code) -> str`(查不到回退空串)、`map(codes) -> dict[str,str]`(批量,一次查)。
- 在返回个股的 API 给响应附 `name` 字段:account positions(块②一并)、`/api/discovery`、`/api/decisions`(list)、`/api/decisions/{id}`、`/api/screener/picks`。(research/track 已有 name。)
- 前端各列表/卡片统一显示 `名称(代码)`(名称缺失时只显示代码)。新增前端小工具 `codeName(name, code)` 或在各处内联。

### 块② 持仓增强(看板)

- 扩展 `PositionOut`(`app/trading/schemas.py`)字段:`name: str`、`buy_date: date | None`、`cost: float`、`last_close: float | None`、`market_value: float | None`、`pnl: float | None`、`pnl_pct: float | None`。
- `GET /api/account/{id}` 计算:
  - `name` = NameLookup;
  - `buy_date` = `min(Trade.traded_at)` where account_id & code & side="BUY"(无则 None);
  - `last_close` = QuoteStore 最新收盘(取该 code 最近一个交易日 close);缺数据 None;
  - `market_value = last_close * shares`;`pnl = (last_close - cost) * shares`;`pnl_pct = (last_close/cost - 1)`(cost>0 时);last_close None 时这些为 None。
- 前端 Dashboard 持仓区(`PositionsTable`)展示:名称(代码)、买入时间、成本、现价、市值、盈亏额+盈亏%(红涨绿跌用 `semanticColor`)。桌面表 / 手机卡(已有 ResponsiveList 模式)。

### 块③ 决策默认自动批准 + 执行

- 新增 `DecisionRunner` 落库后的**自动执行**逻辑(放在 runner 或一个 `auto_execute(session, decision, broker, price)` helper,单测友好):
  - 决策 `status` 落库即 `APPROVED`;
  - 若 action∈{BUY,SELL} 且 shares>0:用该 code **最新收盘价**调 `broker.buy/sell(account_id=1, code, price, shares, as_of)`;资金/持仓不足则捕获异常,decision 仍 APPROVED 但记 `reasoning` 末尾追加「⚠️ 自动执行失败:<原因>」(或新增字段;YAGNI 用 reasoning 追加)。
  - HOLD:不下单,直接 APPROVED。
- `POST /api/decisions/{id}/approve` / `reject` 保留(手动场景仍可用),但默认流程不依赖。
- 前端结论卡:`APPROVED` 状态显示「✅ 已自动执行(action @ 价)」,不显示批准/驳回按钮。

### 块④ 按需异步辩论 + 手动买卖

**异步任务模型**
- 新表 `DecisionJob`(`decision_jobs`):`id`、`code`、`status`(PENDING/RUNNING/DONE/FAILED)、`decision_id`(完成后关联,nullable)、`error`(String,nullable)、`created_at`(date)。
- `POST /api/decisions/run` body `{code}`:校验 code 格式(6 位数字 → 自动补 `.SH/.SZ` 后缀,沿用项目既有 normalize);建 `DecisionJob` PENDING;**用 setsid 后台子进程**启动单只决策脚本(符合本项目 setsid 惯例,避免 uvicorn 内长任务/被回收),立即返回 job。
- 新脚本 `scripts/run_one_decision.py --code <ts_code> --job <id>`:置 job RUNNING → 为该 code 构建 `StockBrief`(复用 build_brief 数据装配)→ `DecisionGraph(...).run` → `DecisionRunner` 落库(走块③自动执行)→ 写 job DONE + decision_id;异常置 FAILED + error。
- `GET /api/decisions/jobs`:返回近期 jobs(进行中 + 最近完成),供前端轮询。

**前端(决策页)**
- 顶部加输入框 + "开始辩论"按钮 → `POST /api/decisions/run`。
- 进行中 jobs 区:轮询 `GET /api/decisions/jobs`(每 ~5s),显示 code+名称+状态;DONE 后刷新决策列表。
- 详情页底部 **手动买/卖面板**:选当前决策的 code,填股数 + 价(默认填最新收盘),按钮调 `POST /api/trade`(现有,body `{account_id:1, code, side, price, shares, on}`),成功后刷新账户。

## 测试

**后端(pytest)**
- 块①:`NameLookup.map/get`;sync 脚本的 upsert 幂等(mock tushare 返回);带 name 的 API 响应。
- 块②:account 端点返回 buy_date/last_close/pnl/pnl_pct 正确(造 trades+positions+quotes);last_close 缺失时字段为 None 不崩。
- 块③:`auto_execute` BUY 扣现金建仓、SELL 减仓、HOLD 不动、资金不足时 decision 仍 APPROVED 且不崩;runner 落库状态为 APPROVED。
- 块④:`POST /api/decisions/run` 建 job 并返回 PENDING;`GET /api/decisions/jobs` 列出;job 状态机(PENDING→RUNNING→DONE/FAILED);code normalize。run_one_decision 用 mock LLM 端到端跑通建 decision+置 DONE。

**前端(vitest)**
- 结论卡:APPROVED 显示「已自动执行」、无批准/驳回按钮。
- 决策页:输入框提交触发 POST;jobs 轮询区渲染进行中条目;手动买卖面板填值提交调 /api/trade。
- 持仓卡/表:显示名称、买入时间、盈亏(红绿)。

## 验收标准

- 决策页输入代号 → 出现"进行中" → 数分钟后该股决策出现在列表且**已自动执行**(账户持仓/现金变化)。
- 详情页可手动买/卖该股,账户即时更新。
- 看板持仓显示 名称(代码)/买入时间/成本/现价/市值/盈亏(红绿)。
- 全站列表与详情的股票都带名称。

## 非目标(YAGNI)

- 不做实时行情(P&L 用日线收盘)。
- 不做任务队列中间件(用 DB job 表 + setsid 子进程足够)。
- 不做撤单/部分成交;PaperBroker 语义不变。
- 不做权限/多账户(固定 account_id=1)。
- 不改既有红涨绿跌/主题/响应式骨架。

## 风险与缓解

- setsid 子进程在容器重启时丢失 → job 停在 RUNNING:脚本启动即写 RUNNING,前端对超时(如 >15min)RUNNING 显示「可能已中断,可重试」;不做自动重试(YAGNI)。
- tushare stock_basic 限频:一次全量调用即可,sync 脚本失败重试少量次数。
- 自动执行误用最新收盘价(非真实成交价)→ 模拟盘可接受,spec 已注明日线制。
