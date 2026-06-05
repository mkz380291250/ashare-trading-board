# 前端深度改版设计:响应式 + 双主题 + 视觉美化

日期:2026-06-05
分支:基于 `feat/decision-detail-page`(含最新决策详情页)

## 背景与问题

前端(React + Vite + antd 6.4)目前:
- **完全没配主题**(用 antd 默认浅蓝),视觉平淡、无品牌感。
- **手机端错乱**:`Layout.Sider breakpoint="lg" collapsedWidth="0"` 在小屏收成 0 宽,但**没有任何按钮能展开**,导致手机上无法导航;各页用写死的 `Col span={8/16}` 不堆叠;antd `Table` 太宽撑爆屏幕横向溢出。

## 目标

深度改版,达到:① 移动端完全可用且美观;② 桌面/移动响应式自适应;③ 深浅双主题(默认深色)可一键切换并持久化;④ 统一的视觉设计语言(品牌色、间距、圆角、字体、卡片样式)。保留 A股「红涨绿跌」色规。

## 用户已确认的决策

- 力度:深度改版(非轻量)。
- 主题:**深浅双主题可切换,默认深色**,切换状态记 `localStorage`。
- 导航:**桌面侧边栏;手机底部 TabBar**(5 项:看板/选股/跟踪/决策/更多;"更多"打开抽屉含研报+回测)。
- 表格:手机端**自动转卡片列表**。
- 品牌强调色:靛蓝 `#5b8cff`。

## 涉及页面/路由(现状,不增删功能)

`/`(Dashboard 交易看板)、`/screener`(选股池)、`/track`(跟踪)、`/decisions`(决策)、`/research`(研报)、`/backtest`(回测)。

## 设计语言(design tokens)

`theme/tokens.ts` 导出两套 antd `ThemeConfig`:

- 公共 token:`colorPrimary = "#5b8cff"`,`borderRadius = 10`,`fontFamily`(系统无衬线栈),`controlHeight`、间距通过组件 token 统一。
- 深色:`algorithm = theme.darkAlgorithm`,`colorBgLayout = "#0f1115"`,`colorBgContainer = "#171a21"`,文字主色高对比、次级降透明度;卡片有细描边 + 轻微提升阴影。
- 浅色:`algorithm = theme.defaultAlgorithm`,`colorBgLayout = "#f5f7fb"`,`colorBgContainer = "#ffffff"`,柔和阴影。
- **A股语义色(与 antd 主题解耦,单独常量)**:`UP = "#f5222d"`(涨/红)、`DOWN = "#13c281"`(跌/绿,深浅主题各取一个对比够的绿)、`FLAT = token.colorTextTertiary`。导出 `semanticColor(value)` 辅助函数,统一给 Tag/Statistic/数字上色。现有 BUY=红/SELL=绿/HOLD=灰沿用此语义。

## 架构与组件

### 1. ThemeProvider(`theme/ThemeProvider.tsx`)
- React Context 暴露 `{ isDark: boolean, toggle: () => void }`。
- 初始值:读 `localStorage["ui-theme"]`,缺省 `"dark"`。
- 渲染 antd `<ConfigProvider theme={isDark ? darkTheme : lightTheme}>`,包住整个 App。
- `toggle` 写回 `localStorage`。
- 在 `main.tsx` 用 `<ThemeProvider>` 包 `<App/>`(替换裸 `ConfigProvider` 缺失现状)。

### 2. 响应式骨架(重写 `App.tsx`)
- 用 antd `Grid.useBreakpoint()` 得到当前断点;定义 `isMobile = !screens.md`(<768px)。
- **桌面(≥md)**:`Layout` = `Sider`(`SideNav` 复用现有 Menu 项)+ `Header`(标题 + `ThemeToggle` 开关)+ `Content`(`<Routes/>`)。
- **手机(<md)**:无 `Sider`;顶部精简 `Header`(标题 + `ThemeToggle`);`Content` 底部留出安全间距;固定底部 `BottomTabBar`。
- 路由表(`Routes`)两端共用,不重复。

### 3. 导航组件
- `components/SideNav.tsx`:桌面侧栏菜单(6 项),`selectedKeys` 跟随 `useLocation`。
- `components/BottomTabBar.tsx`:固定底部,5 个图标项(看板/选股/跟踪/决策/更多),当前路由高亮;点"更多"`onMore()` 打开抽屉。用 antd 图标。
- `components/MoreDrawer.tsx`:antd `Drawer`(从底部或右侧弹出),列出"更多"项(研报、回测),点击导航并关闭。
- `components/ThemeToggle.tsx`:antd `Switch`(带日/月图标),调 `useTheme().toggle`。

### 4. 响应式内容
- **栅格**:各页把 `Col span={N}` 改为响应式 `xs={24} sm={24} md={N}`,手机单列堆叠。
- **`components/ResponsiveList.tsx`**(核心复用件):
  - props:`{ dataSource, columns, rowKey, renderCard(record): ReactNode, onRowClick? }`。
  - 桌面(≥md):渲染 antd `Table`(透传 columns/dataSource/rowKey,`scroll={{x: true}}` 兜底)。
  - 手机(<md):渲染 `dataSource.map(renderCard)` 的卡片列表(每张 antd `Card`,可点)。
  - 用 `Grid.useBreakpoint` 判断。
- 改造用到宽表格的页面(选股池/跟踪/决策列表/研报列表/回测列表)改用 `ResponsiveList`,各自提供 `renderCard`(突出关键字段:代码/名称/涨跌/状态)。

### 5. 视觉打磨
- 卡片统一:圆角、描边/阴影、标题排版、`Statistic` 配色。
- 彩色 Tag、涨跌数字统一走 `semanticColor`。
- 决策页的 `ConclusionCard`/`RoleCard`/`RoleStages`、跟踪/研报/回测页卡片在深浅两主题下都校对对比度。

## 文件清单

**新增**
- `theme/tokens.ts`、`theme/ThemeProvider.tsx`
- `components/ThemeToggle.tsx`、`components/SideNav.tsx`、`components/BottomTabBar.tsx`、`components/MoreDrawer.tsx`、`components/ResponsiveList.tsx`

**修改**
- `main.tsx`(包 ThemeProvider)、`App.tsx`(响应式骨架)
- 6 个页面:栅格响应式化 + 列表页接入 `ResponsiveList`

## 测试(vitest + jsdom)

现有 setup 已 stub `matchMedia`/canvas。为让 `useBreakpoint` 可测,测试中通过设置 `matchMedia` 的匹配结果或对组件注入断点来切换桌面/移动两态(实现时若 `useBreakpoint` 难以驱动,`ResponsiveList`/`BottomTabBar` 接受可选 `forceMobile?` 测试钩子,默认 undefined 走真实断点)。

- `ThemeProvider`:默认 dark;`toggle` 后 `localStorage` 写入且 `isDark` 反转;初始读取 `localStorage` 生效。
- `ResponsiveList`:桌面态渲染出表格列头;移动态渲染出 `renderCard` 的卡片内容(用关键字段断言)。
- `BottomTabBar`:移动态渲染 5 个 Tab;点"更多"触发回调;桌面态不渲染(由 App 控制,测组件本身渲染项即可)。
- `ThemeToggle`:点击调用 `toggle`。
- 各页现有测试同步更新(栅格/表格→ResponsiveList 改动后仍能查到关键文本);全量 `vitest run` + `npm run build` 通过。

## 验收标准

- 手机宽度(<768)下:底部 TabBar 可导航到全部页面(含"更多"里的研报/回测);各页单列堆叠不溢出;宽表格呈卡片列表。
- 桌面:侧栏导航 + 内容多列布局,观感统一。
- 右上开关即时切换深/浅主题,刷新后保持;红涨绿跌正确。
- 不新增/删除任何业务功能;所有现有数据交互(下单、批准/驳回、各列表)行为不变。

## 非目标(YAGNI)

- 不改后端、不改业务逻辑/数据接口。
- 不引入新图表库(ECharts 沿用,仅配色适配)。
- 不做国际化、不做动效系统(仅 antd 自带过渡)。
- 不做服务端渲染。

## 范围说明

改动面较大但属同一内聚目标(主题 + 响应式骨架 + 列表组件 + 逐页接入),作为单一实现计划交付;计划里按"基础设施(主题/骨架/ResponsiveList)→ 逐页接入"分阶段排任务。
