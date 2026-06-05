# 决策详情页设计(每个角色观点 + 结论凸显)

日期:2026-06-05
分支:基于 `feat/tracklist-and-scheduler`(决策功能所在链)

## 背景与问题

多智能体决策引擎(`DecisionGraph`)会让 10+ 个角色(分析师团、多空研究员、交易员、三派风控、风控经理)逐个发言,最终由风控经理裁决出 BUY/SELL/HOLD。

每个角色的发言**已经被持久化**:`DecisionGraph.run()` 把所有角色报告拼成一段 markdown 存进 `decisions.reasoning` 字段,格式为:

```
### 量价分析师
<正文>
```json {"stance":"bull","confidence":0.7} ```

### 基本面分析师
...
### 风控经理
<正文>
```json {"action":"HOLD","confidence":0.62,"shares":0} ```
```

**问题**:现有前端 `DecisionsPanel.tsx` 只是一个表格,展开行把整坨 `reasoning` 原样 pre-wrap 显示——角色不分、立场不明、结论不突出,用户感觉"前端看不到任何信息"。

**目标**:做一个独立的决策详情页,把每个角色的观点清晰表达出来,并把最终结论凸显。

## 范围

- **只做"决策辩论"展示**(用户确认范围 A)。不拼 K 线图、不拼研报独立块(研报观点已由"新闻研报分析师"角色体现)。
- 不改决策的存储方式(`reasoning` 仍是 markdown blob)。只**新增**解析层 + 新端点 + 新前端页。
- 现有列表端点 `GET /api/decisions`、批准/驳回端点保持不变。

## 角色与阶段映射

`DecisionGraph.run()` 中角色出现顺序(rounds=N):

1. 量价分析师 → **阶段:分析师团 (analyst)**
2. 基本面分析师 → analyst
3. 新闻研报分析师 → analyst
4. [多头研究员, 空头研究员] × N 轮 → **阶段:多空辩论 (debate)**
5. 交易员 → **阶段:交易员草案 (trader)**
6. 激进风控 / 保守风控 / 中性风控 → **阶段:风控团 (risk)**
7. 风控经理 → **阶段:最终裁决 (verdict)**

阶段由角色名映射(固定字典),不依赖出现顺序,但保留原始顺序以正确呈现多空辩论的轮次对峙。

立场标签来自每段结尾 json:
- `stance`: `bull`→多(红)、`bear`→空(绿)、`neutral`→中(灰)、`aggressive`→激进、`conservative`→保守
- `action`(交易员/风控经理):`BUY`→红、`SELL`→绿、`HOLD`→灰
- `confidence`: 0–1 浮点

## 后端设计

### 1. 解析器 `app/decision/reasoning_parse.py`(纯函数,可单测)

```
@dataclass
class RoleViewpoint:
    role: str          # 角色名,如 "量价分析师"
    stage: str         # analyst | debate | trader | risk | verdict
    stance: str | None # bull/bear/neutral/aggressive/conservative,或 None
    action: str | None # BUY/SELL/HOLD,或 None(仅交易员/风控经理有)
    confidence: float | None
    text: str          # 去掉 json 围栏后的正文

def parse_reasoning(reasoning: str) -> list[RoleViewpoint]: ...
```

实现要点:
- 用正则按 `^### (角色名)$` 切块(保留出现顺序与重复——多空辩论多轮会有重复角色名)。
- 每块末尾抽 ```` ```json ... ``` ```` 围栏,`json.loads` 解析;失败或缺失则 stance/action/confidence 全 None,正文原样保留。
- 正文 = 去掉末尾 json 围栏后 strip。
- stage 由角色名查固定字典;未知角色名归到 `other`(容错,不抛错)。

边界用例(必测):正常多角色、rounds≥2 多轮重复角色、某段缺 json、json 损坏、裁决型(action)与立场型(stance)混合、空字符串 → 返回 []。

### 2. 新端点 `GET /api/decisions/{id}`(`routes_decisions.py`)

返回:
```
{
  "id": int, "code": str, "name": str | null,
  "action": str, "confidence": float, "shares": int, "status": str,
  "summary": str,            # 风控经理正文首句(到第一个句号/换行)
  "roles": [ {role, stage, stance, action, confidence, text}, ... ]
}
```
- `name`:若 `daily_quotes`/已有名称源可得则填,否则 null(不阻塞)。
- `summary`:从 roles 中 stage==verdict 的 text 取首句;无则空串。
- 找不到 id → 404。

## 前端设计(antd + react-router,沿用研报页左列表右详情布局)

### 路由
- 新增 `/decisions/:id`(react-router 7),页面 `src/pages/DecisionDetailPage.tsx`。
- 左侧决策列表点击 → 跳该路由;无 id 时显示空态/提示选择。

### 页面结构(右侧详情)
1. **结论卡(置顶高亮)** `ConclusionCard`:
   - 大字 BUY/SELL/HOLD,颜色 红/绿/灰;
   - 信心分、建议股数、代码 + 名称、一句话摘要(summary);
   - 右侧 **批准 / 驳回** 按钮(PENDING 才显示;复用现有 approve/reject 端点);
   - 批准弹出价格输入(沿用现有逻辑),操作后刷新。
2. **角色观点(按阶段分组)** `RoleStages`:
   - 4 组顺序渲染:分析师团 / 多空辩论 / 风控团 / 风控经理裁决;(交易员草案作为辩论与风控之间的小节)
   - 每组标题 + 该组角色卡列表;
   - **多空辩论**:按轮次成对呈现多头🔴 vs 空头🟢 的对峙;
   - **风控经理裁决**:整组高亮(与结论卡呼应)。
   - 角色卡 `RoleCard`:角色名 + 立场/动作标签(彩色 Tag)+ 信心(若有)+ 正文。

### 组件边界
- `DecisionDetailPage`:取数(列表 + `/api/decisions/:id`)、布局、approve/reject 交互。
- `ConclusionCard`:纯展示 + 按钮回调(props 驱动)。
- `RoleStages` / `RoleCard`:纯展示,输入 roles 数组,内部分组。

## 测试

**后端**(pytest):
- `parse_reasoning` 单测覆盖上述全部边界用例。
- `GET /api/decisions/{id}`:命中返回结构正确(roles 非空、summary 非空)、404、PENDING 状态字段。

**前端**(vitest + jsdom,沿用现有 matchMedia/canvas stub):
- `RoleStages` 给定 roles 渲染出 4 个分组 + 正确的立场 Tag 颜色;多轮辩论成对出现。
- `ConclusionCard` 渲染 BUY/SELL/HOLD 颜色正确;PENDING 显示批准/驳回,非 PENDING 不显示。

## 验收标准

- 跑过落库的 `run_decisions` 后,前端进决策详情页能看到:每个角色一张卡、立场彩色标签、按阶段分组、最终结论大字高亮,且能批准/驳回。
- 后端解析器对历史 `reasoning` blob(含多轮、缺 json 等)不崩。

## 非目标(YAGNI)

- 不改 `DecisionGraph` 存储结构。
- 不加 K 线、研报独立面板。
- 不做角色发言的流式/实时展示(决策是离线批量跑的)。
