# 切片5(看板增强) 设计:Ant Design 重构 + 研报/回测展示页

日期:2026-06-03
分支:`slice-5-dashboard`(基于 `main`,已含切片0/1/2/3/4 + 选股器 + 回测)

## 背景与目标

现有前端是裸 inline-style 单页长列表(`Dashboard` 堆叠 账户/交易/持仓/净值/机会榜/决策,顶部两个裸 `<button>` 切换 选股池),无 UI 库、无路由。切片4(研报)有 API 但无前端页;切片5(回测)只有脚本打印、无 API 无落库。

目标:用 **Ant Design** 组件库重构看板(中后台现成组件,不手写 CSS、不造轮子),引入路由做多页导航,并补齐研报、回测两类数据的展示页(回测需先补后端落库+API)。

## 关键决策(brainstorm 已确认)

- **UI 库 = Ant Design**(放弃自建 CSS / Tailwind)。TradingAgents-CN 的 web 是 Streamlit(Python),无可复用 React 代码。
- **范围 = 三块都做**:① antd 重构现有两页 + Layout/Menu 导航;② 新增研报展示页;③ 新增回测展示页(含后端回测结果落库 + API)。
- **路由 = react-router**(多页导航)。
- **测试**:后端新增 API/落库 走 pytest TDD;前端引入 **vitest + React Testing Library** 对关键组件做渲染/交互冒烟测,最终靠 `npm run build` 通过 + 跑起来人工验证。
- **YAGNI**:不做暗色切换、不做登录/多账户;回测页展示最新一条 run(全市场 qlib 库未建时用样本 run 数据)。

## 架构

### A. 后端补充(`backend/`,pytest TDD)

1. **回测结果落库** —— ORM `BacktestRun` 表 `backtest_runs`:
   - `id`(PK)、`created_at`(date)、`signal`(str,如 "momentum")、`start`/`end`(date)、`params`(str JSON,如 topk/window)、`strategy_metrics`(str JSON:summarize_report 输出)、`factor_report`(str JSON:factor_report 输出)。
   - `BacktestStore`(`app/backtest/store.py`):`save(run_fields) -> BacktestRun`、`latest() -> BacktestRun|None`、`list_recent(n) -> list[BacktestRun]`。
2. **run_backtest.py 写库** —— 跑完把 strategy+factor 结果存一条(幂等性不强求:每次 run 追加一条,前端展示最新)。新增 `--no-save` 跳过(冒烟用)。
3. **回测 API** —— `app/api/routes_backtest.py`:`GET /api/backtest`(最新一条,无则 404)、`GET /api/backtest/runs?n=10`(近 N 条列表)。注册进 `main.py`。
4. **研报列表 API** —— 现有只有 `GET /api/research/{code}`。新增 `GET /api/research`(列出最新各股笔记:code/as_of/sentiment/rating_consensus/summary/source,按 as_of 倒序),供研报页选股。`ResearchStore` 加 `list_latest(limit) -> list[ResearchNote]`(每股取最新一条)。

### B. 前端(`frontend/`)

依赖:`antd`、`react-router-dom`;dev:`vitest`、`@testing-library/react`、`@testing-library/jest-dom`、`jsdom`。

1. **App 壳** —— `App.tsx` 用 antd `Layout`(`Sider` + `Menu` 四项)+ `react-router` 路由:
   - `/`(或 `/board`)交易看板、`/screener` 选股池、`/research` 研报、`/backtest` 回测。
   - 顶部 `Header` 放标题;`Content` 渲染路由出口。
2. **交易看板页**(`pages/Dashboard.tsx` 重构):
   - 顶部 `Statistic` 卡片行(现金/持仓市值/总资产);`Row`/`Col` 网格布局。
   - 持仓 `Table`(antd,列:代码/股数/成本)、净值 `EquityChart`(保留 ECharts,套 `Card`)。
   - 交易表单 `TradeForm` 用 antd `Form`/`InputNumber`/`Select`/`Button`。
   - 机会榜 `DiscoveryPanel`、决策 `DecisionsPanel` 用 antd `Table`/`Tag`,放各自 `Card`/`Tabs`。
3. **选股池页**(`pages/ScreenerPool.tsx` 重构):antd `Table`,前向收益 T+1/3/5/10 列;`Tag` 标题材。
4. **研报页**(`pages/ResearchPage.tsx` 新):左 `List`/`Table` 选股(从 `GET /api/research`),右 `Card` 展示选中股的 `sentiment`(`Statistic`/进度条着色)、`rating_consensus`、`summary`。
5. **回测页**(`pages/BacktestPage.tsx` 新):
   - `GET /api/backtest` 取最新 run。指标 `Statistic` 卡:年化收益/信息比率/最大回撤/累计收益。
   - 因子区:IC/RankIC/IR 数值 + 分层收益 ECharts 柱状图。
   - run 元信息(signal/区间/params)`Descriptions`。无数据 `Empty` 提示先跑 run_backtest。
6. **公共**:加载态统一 `Spin`、错误/空态 `Empty`;`api/client.ts` 复用(apiGet/apiPost 不动)。

## 数据流

```
后端: run_backtest.py --(save)--> backtest_runs 表
前端: 路由切换 -> 各页 apiGet
  /board     -> /api/account/:id, /api/equity/:id, /api/discovery, /api/decisions
  /screener  -> /api/screener/picks
  /research  -> /api/research (列表) -> /api/research/:code (选中详情, 已有)
  /backtest  -> /api/backtest (最新), /api/backtest/runs (历史)
```

## 错误处理
- 各页 fetch 失败 → `Empty`/提示文案,不白屏(沿用现有 `.catch(()=>{})` 习惯,改为设错误态)。
- 回测/研报无数据 → `Empty` 引导先跑对应脚本。
- 后端 `GET /api/backtest` 无 run → 404;前端转 `Empty`。

## 测试策略
**后端(pytest TDD):**
- `BacktestRun` 模型 roundtrip;`BacktestStore` save/latest/list_recent。
- `ResearchStore.list_latest`(每股取最新、按 as_of 倒序、limit)。
- `GET /api/backtest` / `/api/backtest/runs` / `GET /api/research`(TestClient + StaticPool,沿用 test_api_* 模式)。
- run_backtest 写库:`summarize_report`/`factor_report` 结果可序列化进 `save`(单测 store,不跑 qlib)。

**前端(vitest + RTL,组件渲染/交互冒烟):**
- `App` 路由:点 `Menu` 切换渲染对应页(mock fetch)。
- `BacktestPage`:给定 mock /api/backtest 数据,渲染出指标数值;无数据渲染 `Empty`。
- `ResearchPage`:列表渲染 + 选中后详情渲染(mock fetch)。
- 关键现有组件(`DiscoveryPanel`/`PositionsTable`)antd 化后仍渲染数据。
- 最终:`npm run build`(tsc + vite)通过;`npm run test`(vitest)通过;跑起来人工/截图核对。

## 范围边界(YAGNI)
- 不做暗色主题切换、不做登录/权限/多账户。
- 不改后端既有 API(只新增 backtest/research-list)。
- 回测页只展示最新 + 近期列表,不做参数表单触发回测(回测仍由脚本跑)。
- ECharts 保留,不替换为 antd-charts。
- 不做移动端专门适配(antd 默认响应式即可)。

## 构建顺序(垂直切片,各自 TDD/验证)
后端先行(给前端提供 API):
0 BacktestRun 模型 + BacktestStore → 1 run_backtest 写库 + `/api/backtest` API → 2 `ResearchStore.list_latest` + `GET /api/research` 列表 API。
前端:
3 装 antd+react-router+vitest,配 vitest → 4 App 壳(Layout/Menu/路由)+ 现有两页接入路由(先不重写内部)→ 5 交易看板 antd 化(Statistic/Card/Table/Form)→ 6 选股池 antd 化 → 7 研报页 → 8 回测页(指标卡+因子柱状)→ 9 `npm run build`+vitest 全绿 + 跑起来人工验证截图。
