# 闭环 UI 同步设计:把 Phase 3 数据接进前端

- 日期:2026-06-28
- 状态:已通过 brainstorming,待 writing-plans
- 范围:C(完整)—— 新 API + 两个新页 + Dashboard 健康面板 + 净值图叠加回撤 + Decisions 增强

## 1. 背景与问题

四个 Phase 把后端做成了全自动纸面闭环,但 Phase 3 产出的闭环数据**没有 API 也没有 UI**:
- 决策胜率(`decision_outcomes`)、因子前向 IC/RankIC(`factor_ic_daily`)、策略动作审计(`policy_actions`)完全不可见;
- Decisions 页不体现 qlib 复合分、`LOW_CONF` 状态、弱因子标记;
- 净值图没有回撤叠加。

调度守护进程已在运行(下次 2026-06-29 17:30 北京触发 8 步 run_all),数据会逐日累积。本设计让前端"同步"显示这些闭环信号,以便跑几天后能一眼看出:买卖准不准、因子衰没衰、有没有自动动作、风险态如何。

## 2. 目标 / 非目标

**目标**:把胜率、前向 IC 趋势、策略动作、回撤接进前端;增强 Decisions 与净值图。

**非目标**:不做实时推送(进页加载即可,沿用现状);不做 e2e;不重构现有页面骨架;不接 weixin 投递(后端另议)。

## 3. 技术栈与现状

- 前端:React + TypeScript + Ant Design v6(Card/Statistic/Table/Tag/Col),react-router;图表用 **echarts**(`EquityChart.tsx` 是范本);API 客户端 `api/client.ts` 的 `apiGet`/`apiPost`,同源(`VITE_API_BASE` 默认空)。
- 导航:`SideNav.tsx`(桌面)、`BottomTabBar.tsx` + `MoreDrawer.tsx`(移动),项定义在 `NAV_ALL`/`NAV_MORE`。
- Dashboard 现状:现金/持仓/总值 Statistic、TradeForm、PositionsTable、EquityChart(净值曲线)、DiscoveryPanel(机会榜 Top-8)、DecisionsPanel。
- 后端:FastAPI,一域一路由模块(`routes_account/decisions/discovery/...`),pytest + TestClient(`test_api_*.py`)。

## 4. 后端 API(方案A:一域一模块,扩展现有)

新增两个路由模块:

- `routes_attribution.py`
  - `GET /api/attribution/hit-rate?window=30` → `{window:int, hit_rate:float|null, n:int}`(近窗命中比例 + 样本数;复用 `attribution.outcomes.hit_rate`,n = 窗内 hit 非空的 outcome 数)
  - `GET /api/attribution/forward-ic?days=60` → `[{as_of, ic, rank_ic, n}]`(`factor_ic_daily` 近 days 行升序,喂折线图)
- `routes_policy.py`
  - `GET /api/policy/actions?limit=50` → `[{id, kind, as_of, trigger, detail, status}]`(`policy_actions` 时间倒序;`trigger` 原样返回 JSON 文本由前端解析或直接展示)

扩展现有:

- `GET /api/equity/{account_id}` → 每点加 `drawdown:float`(对历史峰值的当前回撤 = total/累计peak − 1;在 `routes_account` 计算,与 `attribution.equity.current_drawdown` 同语义但逐点)
- `GET /api/discovery` → 每条加 `score:float`、`rank:int`(`DiscoveryPick` 已有,补进响应模型)
- `GET /api/decisions` 列表项加 `confidence:float`;若当日存在该 code 的 `DiscoveryPick` 则加 `score:float|null`(关联当日选股分);`status` 已含 `LOW_CONF`,无需改

所有新端点遵循现有错误处理:查无数据返回空列表 / null 字段,不抛 500。

## 5. 前端新页 + 导航

### 5.1 `/policy` 策略闸(`pages/PolicyPage.tsx`)
- 顶部三 `Statistic` 卡:近30日胜率、最新滚动前向 RankIC(取 forward-ic 最后一行)、当前回撤(取 equity 最后一点 drawdown)
- 主体 antd `Table`(时间倒序):列 = 时间 / 类型 Tag(REMINE 蓝·RISK_OFF 橙·WEAK_SELL 红)/ 触发指标 / 说明 / 状态 Tag(AUTO 绿·PENDING 灰·FAILED 红)
- 空态:"暂无策略动作"

### 5.2 `/attribution` 归因(`pages/AttributionPage.tsx`)
- 顶部:胜率 + 样本数 Statistic
- 中部:`ForwardICChart.tsx`(echarts 双线 ic + rank_ic,叠 0.02 水平阈值参考线 `markLine`)
- 下部:总胜率小表(MVP 只给总胜率与 n;按 BUY/SELL 分组留作后续,不阻塞)

### 5.3 导航
- `NAV_ALL` 加两项(key `/policy` 策略闸、key `/attribution` 归因),图标 `SafetyOutlined` / `LineChartOutlined`
- `NAV_MORE`(移动端 MoreDrawer)同步加两项
- `App.tsx` 的 `<Routes>` 加两条 `<Route>`

### 5.4 组件复用
- 新建 `ForwardICChart.tsx` 复刻 `EquityChart` 的 echarts init/dispose 模式
- 表格/Tag 沿用 DecisionsPage 习惯
- 每页 `useEffect` 内 `apiGet(...).then(set).catch(()=>{})`(沿用 Dashboard 静默失败)

## 6. Dashboard 健康面板 + 净值图叠加回撤

### 6.1 闭环健康卡(`components/HealthPanel.tsx`,置于净值曲线卡上方)
- 一行四 `Statistic`:近30日胜率 / 滚动前向 RankIC / 当前回撤 / 今日策略动作数
- 条件染色:回撤 < −20% 或 胜率 < 40% 时该 `Statistic` 用红 `valueStyle`
- 卡底一行摘要最近一条策略动作(如"6-28 停买:回撤 −22%"),点击 `useNavigate('/policy')`
- 数据并行 `apiGet` 三端点;任一失败该项显示 "—"

### 6.2 `EquityChart.tsx` 增强
- Point 类型加可选 `drawdown?:number`
- echarts 加右侧第二 y 轴 + 一条回撤 area series(负值向下);`drawdown` 缺省则只画净值线(向后兼容,不报错)

## 7. Decisions 页增强(`pages/DecisionsPage.tsx`)

- 表格加两列:**复合分**(`score`,缺省显示"—")、**置信度**(`confidence`,百分比)
- 状态列:`LOW_CONF` 用灰 Tag(区分 APPROVED 绿 / REJECTED 红 / PENDING 默认)
- 详情(若现有详情抽屉/页 reasoning 文本含 `weak_factor`):顶部挂"弱因子"红标。实现取巧:列表项若关联决策的 reasoning 含 `weak_factor` 字串则标记(避免新增字段)

## 8. 测试

**后端(pytest + TestClient,沿用 `test_api_*.py`):**
- `test_api_attribution.py`:seed `decision_outcomes` + `factor_ic_daily`,断言 hit-rate `{hit_rate,n}` 与 forward-ic 数组结构/顺序
- `test_api_policy.py`:seed `policy_actions`,断言列表倒序 + 字段
- `test_api_account.py`(扩展):断言 equity 点含 `drawdown`
- discovery / decisions 扩展字段各加一条断言

**前端(vitest + mock apiGet,沿用 `*.test.tsx`):**
- `PolicyPage.test.tsx`:mock 返回若干 action,断言表格行数 + 类型 Tag 文案 + 空态
- `AttributionPage.test.tsx`:mock 胜率 + IC 序列,断言胜率渲染(图表只断言容器挂载)
- `HealthPanel.test.tsx`:mock 三端点,断言四指标渲染 + 破阈值染色类
- `EquityChart.test.tsx`(扩展):传无 `drawdown` 的点不崩
- `DecisionsPage.test.tsx`(扩展):LOW_CONF 灰 Tag + 复合分列渲染

## 9. 数据流

```
后端表 → 路由模块 → JSON 端点 → apiGet → 页面 useEffect → 组件渲染
decision_outcomes ─ hit_rate() ─ /api/attribution/hit-rate ─┐
factor_ic_daily ─────────────── /api/attribution/forward-ic ─┼─ Attribution/Policy/Health
policy_actions ──────────────── /api/policy/actions ─────────┤
equity_curve(+drawdown) ─────── /api/equity/{id} ────────────┴─ Dashboard EquityChart
discovery_picks(score) ──────── /api/discovery ─────────────── Decisions/机会榜
```

## 10. 实施阶段顺序

1. 后端 API(两个新模块 + 三处扩展 + 测试)—— 独立可验收(curl/pytest)
2. 前端两个新页 + 导航 + ForwardICChart
3. Dashboard 健康面板 + EquityChart 回撤
4. Decisions 增强

每阶段独立可测;前端阶段依赖阶段1的端点。
