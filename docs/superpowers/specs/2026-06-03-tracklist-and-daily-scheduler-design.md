# 跟踪表(Tracklist)+ 每日定时更新 — 设计文档

日期:2026-06-03

## 1. 目标

两个功能,合并交付:

1. **我的跟踪表**:用户粘贴一张股票列表(如同花顺自选导出文本),系统解析出
   代码+名称,以入选当日收盘价为基准,持续跟踪其后续走势。
2. **每日定时更新**:每天 16:00(Asia/Shanghai)自动跑全市场行情 + qlib 重建,
   并刷新跟踪表的各项指标。

与现有 `watch_pool`(由 screener 自动喂入)**分开**:新建独立的跟踪表,避免混淆
两种来源的语义(screener 有 theme/trigger,本功能是用户手动列表)。

## 2. 数据模型

新增表 `tracklist`(SQLAlchemy 模型 `TrackEntry`,放 `app/db/models.py`):

| 字段 | 类型 | 说明 |
|---|---|---|
| code | str(16), PK | 股票代码,如 300975 |
| added_on | date, PK | 入选日期(=入选收盘价对应交易日) |
| name | str(32) | 股票名称 |
| entry_close | float | 入选日收盘价(基准) |
| ret_t1 / ret_t3 / ret_t5 / ret_t10 | float\|None | 入选后 T+1/3/5/10 收益(A) |
| last_close | float\|None | 最新收盘价 |
| ret_since | float\|None | 至今涨跌幅(B) |
| max_gain | float\|None | 入选以来最大涨幅(B) |
| max_drawdown | float\|None | 入选以来最大回撤(B) |
| last_updated | date\|None | 指标最近刷新对应的交易日 |

复合主键 (code, added_on):同一只股票若在不同日期再次加入,各自独立跟踪。

## 3. 组件

### 3.1 文本解析器 `app/screener/tracklist_parser.py`
- 输入:粘贴的任意文本(同花顺自选页面的复制内容)。
- 输出:`list[(code, name)]`,去重。
- 规则:用正则抓 6 位数字代码;名称取代码同行或相邻行的中文词;无法配名称时
  name 置空。对非 A 股代码(港股/美股/期货行)忽略——只保留 6 位数字 A 股代码。
- 纯函数,单元测试覆盖用户给的样例文本。

### 3.2 跟踪服务 `app/screener/tracklist.py`(`Tracker` 类)
- `add(codes_with_names, on, closes)`:写入条目,entry_close 取该交易日收盘;
  幂等(同 code+added_on 已存在则跳过)。
- `update_metrics(code, added_on, bars)`:给定入选日起的日线序列,计算
  - T+1/3/5/10:复用 `app/screener/filters.py::forward_return`
  - last_close / ret_since / max_gain / max_drawdown
- `list()` / `remove(code, added_on)`。
- 收益口径:基于**后复权**收盘(沿用项目现有 `app/data/adjust.py` 口径,与
  watch_pool 一致),保证跨除权日可比。

### 3.3 API 路由 `app/api/routes_tracklist.py`(prefix `/track`)
- `POST /track` body `{text: str}` → 解析 + 入选(入选日=DB 最新交易日),返回新增列表。
- `GET /track` → 全部条目(按 added_on desc)。
- `DELETE /track/{code}/{added_on}` → 删除单条。
- 在 `app/main.py` 注册 router。

### 3.4 前端页 `frontend/src/pages/TrackPage.tsx`
- 上方:粘贴框 + "添加跟踪"按钮 → POST /track。
- 下方:表格列出 code/name/entry_close/T+1·3·5·10/至今/最大涨幅/最大回撤/更新日。
- 每行删除按钮。接入 `frontend/src/api`。导航加入口。

### 3.5 编排脚本 `scripts/daily_full.py`
依次执行(任一步失败记录日志但继续后续可独立的步骤):
1. 全市场行情更新 — 复用 `daily_update_quotes.py` 逻辑(增量,跳过已入库交易日)。
2. qlib 重建 — 复用 `build_qlib_data.py`(全市场)。
3. 跟踪表刷新 — 对每条 tracklist 拉入选日至今日线,调 `Tracker.update_metrics`。

可命令行手动运行;也被调度器调用。

### 3.6 调度器
- 后端进程内置 **APScheduler**(`BackgroundScheduler`),在 `app/main.py` 的
  startup 钩子注册一个 cron job:`hour=16, minute=0, timezone="Asia/Shanghai"`,
  回调执行 `daily_full` 的入口函数。
- 通过设置开关(env / config)可禁用,便于本地开发与测试时不自动触发。

## 4. 数据流

粘贴文本 → 解析器 → Tracker.add(入选日=DB最新交易日, 收盘=DailyQuote)→ tracklist 表。

每日 16:00 → daily_full:行情入库 → qlib 重建 → 逐条 update_metrics → tracklist 指标更新 → 前端 GET /track 展示。

## 5. 错误处理
- 解析器:无有效代码时返回空列表,API 返回 200 + 空 added 列表(不报错)。
- daily_full:每步 try/except + 日志;一步失败不阻断其余步骤;退出码非 0 以便排查。
- 调度器:job 异常被 APScheduler 捕获并记录,不影响后端服务。
- 行情/qlib 步骤沿用现有脚本的限频与断点续跑特性。

## 6. 测试
- `tracklist_parser`:用本对话中用户粘贴的同花顺样例做断言(应得 10 只:300975
  商络电子 / 603045 福达合金 / 601991 大唐发电 / 300666 江丰电子 / 300184 力源信息
  / 688519 南亚新材 / 688257 新锐股份 / 301099 雅创电子 / 301338 凯格精机 /
  300486 东杰智能)。
- `Tracker`:add 幂等、forward returns、ret_since/max_gain/max_drawdown 计算。
- API:POST/GET/DELETE(沿用 `tests/test_watch_pool.py`、`test_api_screener.py` 模式)。
- 调度器:注入假时钟/直接调 daily_full 入口函数验证编排顺序,不依赖真实定时。
- 前端:TrackPage 渲染 + 提交冒烟测试(沿用 `ScreenerPool.test.tsx` 模式)。

## 7. 不做(YAGNI)
- 不做盘中实时跟踪(只用盘后日线)。
- 不做多用户/权限。
- 不改现有 watch_pool 行为。
- 不做导出/告警推送(后续可加)。
