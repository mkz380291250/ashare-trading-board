# 切片4 设计:研报财报分析(质化信号源 + 决策研报分析师)

日期:2026-06-03
分支:`slice-4`(基于 `main`,已含切片0/1/2/3 + 题材选股器)

## 目标

把券商研报、新闻资讯经 LLM 消化成结构化「研报笔记」,作为:
1. **发现引擎的质化信号源**(可插拔 SignalProvider,兑现切片0「后插不返工」承诺)
2. **决策引擎「新闻研报分析师」的数据源**(此前是空 stub)

落地为缓存表,发现/决策从库读,扫描/决策时不打网络(沿用切片2/3 模式)。

## 关键决策(brainstorm 已确认)

- **数据源 = 两者结合**:tushare(`report_rc` 券商评级/目标价 + `news`,用户高积分)+ scrapling/requests 爬 eastmoney datacenter 新闻资讯(沿用切片2 验证可用的 JSON 接口;同花顺/push2 已知被反爬挡死,不走)。
- **股票范围 = 持仓 ∪ 最新发现Top8 ∪ 选股池**(有界,几十只;全市场逐只不现实,有限流)。
- **分析输出 = 情绪分 + 评级共识 + 摘要**:每只股 `sentiment(-1~1)` + `rating_consensus`(评级/目标价聚合)+ `summary`(中文摘要)。一份数据两边都用。
- **发现接法 = 稀疏因子(改 scorer)**:研报作为可插拔质化因子接入打分器;scorer 由「所有因子取交集」改为「并集 + 缺失因子按中性 0.5 填充」。
- **LLM = 可配置切换,默认 local(Claude)**:ResearchAnalyzer 复用 decision 的 `LLMClient` 抽象(`LocalClaudeClient`/`DeepSeekClient`)。`research_llm` 配置项,默认 `local`,可切 `deepseek`。与决策引擎一致。

## 架构

新模块 `backend/app/research/`:

### 1. sources.py — 原始研报/新闻抓取
- `ResearchSource`(ABC):`fetch(code, as_of) -> list[ResearchItem]`。
- `ResearchItem`(dataclass):`title, text, date, rating(可选), target_price(可选), source`。
- `TushareResearchSource`:`report_rc`(券商评级/目标价)+ `news`/`major_news`(新闻),注入式 `pro` 句柄便于测试。限流复用 `RateLimiter`(historical-quote-db 已有,滑窗)。
- `EastMoneyNewsSource`:datacenter-web JSON(沿用切片2 `datacenter_board_members` 同款 requests + 重试4次模式),失败返 `[]` 兜底,不抛。
- 组合:`CompositeSource` 合并多源条目(去重按 title)。

### 2. analyzer.py — LLM 消化为结构化笔记
- `ResearchNote`(dataclass):`code, as_of, sentiment(float -1~1), rating_consensus(str), summary(str), source(str)`。
- `ResearchAnalyzer(llm: LLMClient)`:`analyze(code, items, as_of) -> ResearchNote`。
  - 拼 prompt(条目标题+正文+评级),要求结尾输出 JSON `{sentiment, rating_consensus, summary}`,用 `parse_verdict`(复用 decision/llm.py)解析。
  - 空 items → 直接返中性笔记(sentiment 0,summary「数据缺失」),不调 LLM。
  - LLM 解析失败 → sentiment 0 兜底 + 原始文本截断进 summary。

### 3. models.py + store.py — 持久化
- ORM `ResearchNote` 表 `research_notes`:`code`+`as_of` 复合主键,`sentiment Float`,`rating_consensus String`,`summary String`,`source String`,索引 `as_of`。
- `ResearchStore`:`upsert(note)` 幂等(同 code+as_of 覆盖)、`latest(code) -> ResearchNote|None`(取该股最新)、`latest_map(codes) -> dict[code, note]`。

### 4. runner.py — 日度刷新
- `ResearchRunner(source, analyzer, store)`:
  - `run(universe: set[str], as_of)`:逐只 fetch→analyze→upsert。
  - universe 由调用方传入(持仓 ∪ 最新 discovery_picks ∪ watch_pool)。
  - 幂等:同 (code, as_of) 重跑覆盖。限流由 source 内部处理。

### 5. 发现引擎集成
- `ResearchSignalProvider(SignalProvider)`(放 `app/discovery/providers.py` 或 research 模块):
  - 构造注入 `ResearchStore`。`compute(snapshot)` 读 snapshot 内各 code 的最新笔记 → 返回 `{"research_sent": {code: sentiment}}`,只对**有笔记**的 code 给值(稀疏)。
- **scorer 改造**(`app/discovery/scorer.py`):
  - 旧:`common = ∩ 各因子 code`,只给全因子齐全的股打分。
  - 新:`universe = ∪ 各因子 code`;某股缺某因子时,该因子的百分位按**中性 0.5** 计入(不偏不倚)。
  - 保证:无研报覆盖的股票 research 因子=0.5,不受惩罚;正情绪股获加成。
  - **回归**:仅有动量因子(全股齐全)时,并集=交集,结果与切片2 完全一致(回归测试锁定)。
- 注册:`run_discovery.py` 把 `ResearchSignalProvider` 与 `MomentumProvider` 一起传给 scorer(权重可配)。

### 6. 决策引擎集成
- `build_brief`(`app/decision/brief.py`)加 `research: dict | None` 参数;`StockBrief` 加 `research` 字段;`to_prompt` 增「研报观点」段(summary + sentiment + rating_consensus),无则「无研报数据」。
- `新闻研报分析师` role prompt(`app/decision/agents.py`)改为:基于 brief 的研报段给观点,无数据时说明缺失保持中性(行为同现状,但现在有数据了)。
- `run_decisions.py`:构造 `ResearchStore`,build_brief 时填入 `store.latest(code)`。

### 7. API + 脚本
- `GET /api/research/{code}`:返回该股最新笔记(无则 404 / 空)。注册进 `main.py`。
- `scripts/run_research.py`:组装 universe(持仓∪最新发现∪选股池)→ ResearchRunner.run。

### 8. config(`app/config.py`)
- `research_llm: str = "local"`(local | deepseek)。
- `research_max_per_min: int = 50`(tushare 研报接口限流,保守默认;历史库经验 ≤100/min)。
- 复用现有 deepseek_*/claude_bin。

## 数据流

```
日度: run_discovery (动量, 可含上轮research) → discovery_picks
      run_screener → watch_pool
      run_research(持仓∪discovery_picks∪watch_pool):
          各源 fetch → ResearchAnalyzer(LLM) → research_notes
      下一轮 run_discovery 的 ResearchSignalProvider 读 research_notes (T-1 滞后)
决策: run_decisions → build_brief 填 research_notes.latest → 新闻研报分析师
```

**循环依赖处理**:研报范围含「发现Top8」,但研报跑在发现**之后**;ResearchSignalProvider 用**已有(上一轮)**笔记,无则中性。因此发现→研报→下一轮发现,单向无环。

## 错误处理
- 任一源抓取失败 → 该源返 `[]`,不阻断其他源/其他股。
- LLM 失败/解析失败 → 中性笔记兜底,流程不崩。
- 限流:source 内部 RateLimiter;runner 不并发打源。

## 测试策略(TDD,先测后码)
- `sources`:注入假 `pro`/假 fetch → 条目解析、空结果、异常返 []。
- `analyzer`:注入假 LLMClient → JSON 解析成功/失败兜底/空输入中性。
- `store`:upsert 幂等(重复 code+as_of 覆盖)、latest/latest_map。
- `ResearchSignalProvider`:稀疏输出(只覆盖有笔记的 code)。
- **scorer**:① 并集+中性填充新行为;② **仅动量因子时结果 == 切片2(回归锁定)**。
- `brief`:研报段渲染(有/无数据)。
- `graph`:新闻研报分析师读到 brief 研报数据。
- **冒烟**:真实 tushare `report_rc` + 真实 LLM 对 1-2 只股跑通,人工核摘要合理。

## 范围边界(YAGNI)
- 不做财报深度建模:财务指标(fina_indicator)已在决策 fundamentals/选股器用,本切片「财报」聚焦研报中的财务观点文本,不重复造数值管线。
- 不做全市场研报库(限流不现实)。
- 不做研报历史回测(单独可后续)。
- API 仅最新笔记查询,不做分页/检索。

## 构建顺序(垂直切片,各自 TDD)
0 config + research_notes 模型/store → 1 sources(tushare+eastmoney)→ 2 analyzer → 3 runner → 4 scorer 改造(并集+中性,回归)→ 5 ResearchSignalProvider + 接入 run_discovery → 6 决策 brief/agent 接入 → 7 API + run_research 脚本 → 8 冒烟验证。
