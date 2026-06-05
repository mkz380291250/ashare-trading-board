# 决策详情页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把多智能体决策的每个角色观点结构化展示在独立详情页,并凸显最终结论(BUY/SELL/HOLD)。

**Architecture:** 后端不改存储——新增纯函数 `parse_reasoning` 把 `decisions.reasoning` 的 markdown blob 解析成结构化角色列表,新增 `GET /api/decisions/{id}` 返回结构化详情。前端沿用研报页"单页左列表右详情"模式,新增 `/decisions` 页:顶部结论卡 + 角色卡按 5 阶段分组。

**Tech Stack:** 后端 FastAPI + SQLAlchemy + pytest;前端 React + antd + react-router-dom + vitest。

---

## 文件结构

- Create `backend/app/decision/reasoning_parse.py` — 解析器(纯函数 + dataclass)
- Create `backend/tests/test_reasoning_parse.py` — 解析器单测
- Modify `backend/app/api/routes_decisions.py` — 加 `GET /api/decisions/{id}`
- Modify `backend/tests/test_api_decisions.py` — 加详情端点测试
- Create `frontend/src/components/RoleCard.tsx` — 单角色卡(+ Role 类型)
- Create `frontend/src/components/RoleStages.tsx` — 按阶段分组渲染
- Create `frontend/src/components/RoleStages.test.tsx`
- Create `frontend/src/components/ConclusionCard.tsx` — 结论高亮卡(+ Conclusion 类型)
- Create `frontend/src/components/ConclusionCard.test.tsx`
- Create `frontend/src/pages/DecisionsPage.tsx` — 页面装配
- Create `frontend/src/pages/DecisionsPage.test.tsx`
- Modify `frontend/src/App.tsx` — 加菜单项 + 路由

---

### Task 1: 后端解析器 `parse_reasoning`

**Files:**
- Create: `backend/app/decision/reasoning_parse.py`
- Test: `backend/tests/test_reasoning_parse.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_reasoning_parse.py
from app.decision.reasoning_parse import parse_reasoning

SAMPLE = (
    "### 量价分析师\n动量强,放量突破。\n```json {\"stance\":\"bull\",\"confidence\":0.7} ```\n\n"
    "### 空头研究员\n高位接盘风险。\n```json {\"stance\":\"bear\",\"confidence\":0.6} ```\n\n"
    "### 风控经理\n空仓观望,不接刀。\n```json {\"action\":\"HOLD\",\"confidence\":0.62,\"shares\":0} ```"
)


def test_splits_each_role_in_order():
    vps = parse_reasoning(SAMPLE)
    assert [v.role for v in vps] == ["量价分析师", "空头研究员", "风控经理"]


def test_extracts_stance_and_strips_json_fence():
    v = parse_reasoning(SAMPLE)[0]
    assert v.stance == "bull"
    assert v.confidence == 0.7
    assert v.stage == "analyst"
    assert "json" not in v.text and v.text == "动量强,放量突破。"


def test_verdict_role_has_action_and_stage():
    v = parse_reasoning(SAMPLE)[2]
    assert v.action == "HOLD"
    assert v.stage == "verdict"
    assert v.stance is None


def test_missing_or_broken_json_is_tolerated():
    txt = "### 交易员\n没有结尾json的发言\n\n### 多头研究员\n坏的\n```json {不是json} ```"
    vps = parse_reasoning(txt)
    assert vps[0].action is None and vps[0].text == "没有结尾json的发言"
    assert vps[0].stage == "trader"
    assert vps[1].stance is None  # 解析失败但不抛错
    assert vps[1].stage == "debate"


def test_multi_round_debate_keeps_duplicates_in_order():
    txt = ("### 多头研究员\n第一轮多\n```json {\"stance\":\"bull\",\"confidence\":0.5} ```\n\n"
           "### 空头研究员\n第一轮空\n```json {\"stance\":\"bear\",\"confidence\":0.5} ```\n\n"
           "### 多头研究员\n第二轮多\n```json {\"stance\":\"bull\",\"confidence\":0.6} ```")
    roles = [v.role for v in parse_reasoning(txt)]
    assert roles == ["多头研究员", "空头研究员", "多头研究员"]


def test_empty_returns_empty_list():
    assert parse_reasoning("") == []
    assert parse_reasoning("   ") == []


def test_unknown_role_maps_to_other():
    assert parse_reasoning("### 某个新角色\n内容")[0].stage == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_reasoning_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.decision.reasoning_parse'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/decision/reasoning_parse.py
import json
import re
from dataclasses import dataclass

STAGE_MAP = {
    "量价分析师": "analyst",
    "基本面分析师": "analyst",
    "新闻研报分析师": "analyst",
    "多头研究员": "debate",
    "空头研究员": "debate",
    "交易员": "trader",
    "激进风控": "risk",
    "保守风控": "risk",
    "中性风控": "risk",
    "风控经理": "verdict",
}

_HEADER = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_JSON_FENCE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class RoleViewpoint:
    role: str
    stage: str
    stance: str | None
    action: str | None
    confidence: float | None
    text: str


def parse_reasoning(reasoning: str) -> list[RoleViewpoint]:
    if not reasoning or not reasoning.strip():
        return []
    out: list[RoleViewpoint] = []
    headers = list(_HEADER.finditer(reasoning))
    for i, m in enumerate(headers):
        role = m.group(1).strip()
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(reasoning)
        block = reasoning[start:end]
        stance = action = confidence = None
        fence = _JSON_FENCE.search(block)
        if fence:
            try:
                data = json.loads(fence.group(1))
                stance = data.get("stance")
                action = data.get("action")
                c = data.get("confidence")
                confidence = float(c) if c is not None else None
            except (ValueError, TypeError):
                pass
            text = block[: fence.start()].strip()
        else:
            text = block.strip()
        out.append(RoleViewpoint(role=role, stage=STAGE_MAP.get(role, "other"),
                                 stance=stance, action=action,
                                 confidence=confidence, text=text))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_reasoning_parse.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/decision/reasoning_parse.py backend/tests/test_reasoning_parse.py
git commit -m "feat(decision): parse reasoning blob into structured role viewpoints"
```

---

### Task 2: 后端 `GET /api/decisions/{id}` 端点

**Files:**
- Modify: `backend/app/api/routes_decisions.py`
- Test: `backend/tests/test_api_decisions.py`

- [ ] **Step 1: Write the failing test**

该文件用 `_client()` 辅助函数(返回 `(client, s)`)建内存库,**不是 pytest fixture**。追加下面两个测试,复用同样的 `_client()` 与 `date`/`Decision`(文件顶部已 import):

```python
# 追加到 backend/tests/test_api_decisions.py 末尾

_REASON = (
    "### 量价分析师\n放量突破。\n```json {\"stance\":\"bull\",\"confidence\":0.7} ```\n\n"
    "### 风控经理\n空仓观望,不接刀。\n```json {\"action\":\"HOLD\",\"confidence\":0.6,\"shares\":0} ```"
)


def test_get_decision_detail_returns_structured_roles():
    client, s = _client()
    d = Decision(as_of=date(2026, 6, 4), code="600519.SH", action="HOLD",
                 confidence=0.6, shares=0, reasoning=_REASON,
                 status="PENDING", created_at=date(2026, 6, 4))
    s.add(d); s.commit()
    body = client.get(f"/api/decisions/{d.id}").json()
    assert body["action"] == "HOLD"
    assert body["status"] == "PENDING"
    assert body["summary"].startswith("空仓观望")
    roles = body["roles"]
    assert [x["role"] for x in roles] == ["量价分析师", "风控经理"]
    assert roles[0]["stance"] == "bull" and roles[0]["stage"] == "analyst"
    assert roles[1]["stage"] == "verdict"


def test_get_decision_404():
    client, _ = _client()
    assert client.get("/api/decisions/99999").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/pytest tests/test_api_decisions.py -k detail -v`
Expected: FAIL — 路由不存在,返回 404 但结构断言失败(或 405)

- [ ] **Step 3: Write minimal implementation**

在 `backend/app/api/routes_decisions.py` 顶部 import 处加 `import re` 和解析器,并在 `list_decisions` 之后、approve 之前加端点:

```python
import re
from app.decision.reasoning_parse import parse_reasoning


@router.get("/decisions/{decision_id}")
def get_decision(decision_id: int, s: Session = Depends(get_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    roles = parse_reasoning(d.reasoning)
    verdict_text = next((r.text for r in roles if r.stage == "verdict"), "")
    summary = re.split(r"[。\n]", verdict_text.strip(), maxsplit=1)[0] if verdict_text else ""
    return {
        "id": d.id, "code": d.code, "name": None,
        "action": d.action, "confidence": d.confidence, "shares": d.shares,
        "status": d.status, "summary": summary,
        "roles": [{"role": r.role, "stage": r.stage, "stance": r.stance,
                   "action": r.action, "confidence": r.confidence, "text": r.text}
                  for r in roles],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pytest tests/test_api_decisions.py -v`
Expected: PASS（含原有列表测试 + 2 个新测试)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes_decisions.py backend/tests/test_api_decisions.py
git commit -m "feat(api): GET /api/decisions/{id} returns structured role viewpoints"
```

---

### Task 3: 前端角色卡 `RoleCard` + 分组 `RoleStages`

**Files:**
- Create: `frontend/src/components/RoleCard.tsx`
- Create: `frontend/src/components/RoleStages.tsx`
- Test: `frontend/src/components/RoleStages.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/RoleStages.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RoleStages } from "./RoleStages";

const ROLES = [
  { role: "量价分析师", stage: "analyst", stance: "bull", action: null, confidence: 0.7, text: "放量突破" },
  { role: "多头研究员", stage: "debate", stance: "bull", action: null, confidence: 0.6, text: "买入" },
  { role: "空头研究员", stage: "debate", stance: "bear", action: null, confidence: 0.5, text: "风险" },
  { role: "风控经理", stage: "verdict", stance: null, action: "HOLD", confidence: 0.62, text: "观望" },
];

describe("RoleStages", () => {
  it("renders stage groups and role text", () => {
    render(<RoleStages roles={ROLES} />);
    expect(screen.getByText("分析师团")).toBeInTheDocument();
    expect(screen.getByText("多空辩论")).toBeInTheDocument();
    expect(screen.getByText("风控经理裁决")).toBeInTheDocument();
    expect(screen.getByText("放量突破")).toBeInTheDocument();
    // 立场标签:多头一个"多"、空头一个"空"
    expect(screen.getAllByText("多").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("空")).toBeInTheDocument();
  });

  it("omits empty stages", () => {
    render(<RoleStages roles={[ROLES[0]]} />);
    expect(screen.queryByText("风控团")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/RoleStages.test.tsx`
Expected: FAIL — 找不到模块 `./RoleStages`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/RoleCard.tsx
import { Card, Tag } from "antd";

export type Role = {
  role: string; stage: string; stance: string | null;
  action: string | null; confidence: number | null; text: string;
};

const LABEL: Record<string, { t: string; c: string }> = {
  bull: { t: "多", c: "red" },
  bear: { t: "空", c: "green" },
  neutral: { t: "中", c: "default" },
  aggressive: { t: "激进", c: "volcano" },
  conservative: { t: "保守", c: "blue" },
  BUY: { t: "BUY", c: "red" },
  SELL: { t: "SELL", c: "green" },
  HOLD: { t: "HOLD", c: "default" },
};

export function RoleCard({ r }: { r: Role }) {
  const tag = LABEL[r.action ?? r.stance ?? ""];
  return (
    <Card size="small" style={{ marginBottom: 8 }} title={
      <span>
        {r.role}
        {tag && <Tag color={tag.c} style={{ marginLeft: 8 }}>{tag.t}</Tag>}
        {r.confidence != null && (
          <span style={{ fontWeight: 400, marginLeft: 8 }}>信心 {r.confidence.toFixed(2)}</span>
        )}
      </span>
    }>
      <div style={{ whiteSpace: "pre-wrap" }}>{r.text}</div>
    </Card>
  );
}
```

```tsx
// frontend/src/components/RoleStages.tsx
import { Typography } from "antd";
import { RoleCard, type Role } from "./RoleCard";

export type { Role };

const STAGES = [
  { key: "analyst", label: "分析师团" },
  { key: "debate", label: "多空辩论" },
  { key: "trader", label: "交易员草案" },
  { key: "risk", label: "风控团" },
  { key: "verdict", label: "风控经理裁决" },
];

export function RoleStages({ roles }: { roles: Role[] }) {
  return (
    <div>
      {STAGES.map((st) => {
        const items = roles.filter((r) => r.stage === st.key);
        if (!items.length) return null;
        return (
          <div key={st.key} data-testid={`stage-${st.key}`} style={{ marginTop: 16 }}>
            <Typography.Title level={5}
              style={st.key === "verdict" ? { color: "#d4380d" } : undefined}>
              {st.label}
            </Typography.Title>
            {items.map((r, i) => <RoleCard key={`${r.role}-${i}`} r={r} />)}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/RoleStages.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RoleCard.tsx frontend/src/components/RoleStages.tsx frontend/src/components/RoleStages.test.tsx
git commit -m "feat(frontend): RoleCard + RoleStages grouped role viewpoints"
```

---

### Task 4: 前端结论卡 `ConclusionCard`

**Files:**
- Create: `frontend/src/components/ConclusionCard.tsx`
- Test: `frontend/src/components/ConclusionCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ConclusionCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ConclusionCard } from "./ConclusionCard";

const BASE = { id: 1, code: "600519.SH", name: "贵州茅台", action: "BUY",
  confidence: 0.7, shares: 100, summary: "低估值买入" };

describe("ConclusionCard", () => {
  it("shows action and approve/reject when PENDING", () => {
    render(<ConclusionCard c={{ ...BASE, status: "PENDING" }}
      onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("低估值买入")).toBeInTheDocument();
    expect(screen.getByText("批准")).toBeInTheDocument();
    expect(screen.getByText("驳回")).toBeInTheDocument();
  });

  it("hides buttons when not PENDING", () => {
    render(<ConclusionCard c={{ ...BASE, status: "APPROVED" }}
      onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.queryByText("批准")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ConclusionCard.test.tsx`
Expected: FAIL — 找不到模块 `./ConclusionCard`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/ConclusionCard.tsx
import { useState } from "react";
import { Card, Tag, Statistic, Row, Col, Button, Space, InputNumber } from "antd";

export type Conclusion = {
  id: number; code: string; name: string | null; action: string;
  confidence: number; shares: number; status: string; summary: string;
};

const ACTION_COLOR: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };

export function ConclusionCard({ c, onApprove, onReject }: {
  c: Conclusion; onApprove: (price: number) => void; onReject: () => void;
}) {
  const [price, setPrice] = useState(0);
  return (
    <Card style={{ marginBottom: 16 }}>
      <Row align="middle" gutter={16}>
        <Col flex="auto">
          <Tag color={ACTION_COLOR[c.action] || "default"}
            style={{ fontSize: 28, padding: "4px 16px", lineHeight: "40px" }}>
            {c.action}
          </Tag>
          <span style={{ fontSize: 18, marginLeft: 12 }}>{c.code} {c.name ?? ""}</span>
          <div style={{ marginTop: 8 }}>{c.summary}</div>
        </Col>
        <Col><Statistic title="信心" value={c.confidence} precision={2} /></Col>
        <Col><Statistic title="建议股数" value={c.shares} /></Col>
        {c.status === "PENDING" && (
          <Col>
            <Space>
              <InputNumber placeholder="成交价" value={price}
                onChange={(v) => setPrice(v ?? 0)} />
              <Button type="primary" onClick={() => onApprove(price)}>批准</Button>
              <Button danger onClick={onReject}>驳回</Button>
            </Space>
          </Col>
        )}
      </Row>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ConclusionCard.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConclusionCard.tsx frontend/src/components/ConclusionCard.test.tsx
git commit -m "feat(frontend): ConclusionCard highlighting BUY/SELL/HOLD verdict"
```

---

### Task 5: 前端 `DecisionsPage` 装配 + 路由 + 菜单

**Files:**
- Create: `frontend/src/pages/DecisionsPage.tsx`
- Create: `frontend/src/pages/DecisionsPage.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/DecisionsPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DecisionsPage } from "./DecisionsPage";

const LIST = [{ id: 1, code: "600519.SH", action: "HOLD", status: "PENDING" }];
const DETAIL = {
  id: 1, code: "600519.SH", name: null, action: "HOLD", confidence: 0.62,
  shares: 0, status: "PENDING", summary: "空仓观望",
  roles: [{ role: "量价分析师", stage: "analyst", stance: "bull",
    action: null, confidence: 0.7, text: "放量突破" }],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const body = /\/api\/decisions\/1$/.test(url) ? DETAIL : LIST;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }) as any);
});

describe("DecisionsPage", () => {
  it("loads list then detail with role viewpoints", async () => {
    render(<DecisionsPage />);
    await waitFor(() => expect(screen.getByText("空仓观望")).toBeInTheDocument());
    expect(screen.getByText("分析师团")).toBeInTheDocument();
    expect(screen.getByText("放量突破")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/DecisionsPage.test.tsx`
Expected: FAIL — 找不到模块 `./DecisionsPage`

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/pages/DecisionsPage.tsx
import { useEffect, useState, useCallback } from "react";
import { Row, Col, Card, Table, Tag, Empty } from "antd";
import { apiGet, apiPost } from "../api/client";
import { ConclusionCard, type Conclusion } from "../components/ConclusionCard";
import { RoleStages } from "../components/RoleStages";
import type { Role } from "../components/RoleCard";

type ListItem = { id: number; code: string; action: string; status: string };
type Detail = Conclusion & { roles: Role[] };

const ACTION_COLOR: Record<string, string> = { BUY: "red", SELL: "green", HOLD: "default" };

export function DecisionsPage() {
  const [rows, setRows] = useState<ListItem[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);

  const loadList = useCallback(() => {
    apiGet<ListItem[]>("/api/decisions").then((r) => {
      setRows(r);
      setSel((cur) => (cur == null && r[0] ? r[0].id : cur));
    }).catch(() => {});
  }, []);
  useEffect(() => { loadList(); }, [loadList]);

  const loadDetail = useCallback((id: number) => {
    apiGet<Detail>(`/api/decisions/${id}`).then(setDetail).catch(() => {});
  }, []);
  useEffect(() => { if (sel != null) loadDetail(sel); }, [sel, loadDetail]);

  async function act(what: "approve" | "reject", price = 0) {
    if (sel == null) return;
    await apiPost(`/api/decisions/${sel}/${what}`, what === "approve" ? { price } : {});
    loadList(); loadDetail(sel);
  }

  const columns = [
    { title: "代码", dataIndex: "code", key: "code" },
    { title: "动作", dataIndex: "action", key: "action",
      render: (a: string) => <Tag color={ACTION_COLOR[a] || "default"}>{a}</Tag> },
    { title: "状态", dataIndex: "status", key: "status" },
  ];

  return (
    <Row gutter={16}>
      <Col span={8}>
        <Card title="决策列表">
          {rows.length ? (
            <Table rowKey="id" size="small" pagination={false} dataSource={rows}
              columns={columns}
              onRow={(r) => ({ onClick: () => setSel(r.id), style: { cursor: "pointer" } })} />
          ) : <Empty description="暂无决策,先跑 run_decisions.py" />}
        </Card>
      </Col>
      <Col span={16}>
        {detail ? (
          <>
            <ConclusionCard c={detail}
              onApprove={(p) => act("approve", p)} onReject={() => act("reject")} />
            <RoleStages roles={detail.roles} />
          </>
        ) : <Empty description="选择左侧决策查看辩论" />}
      </Col>
    </Row>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/DecisionsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: 接入路由与菜单**

在 `frontend/src/App.tsx`:
1. 顶部加 import:`import { DecisionsPage } from "./pages/DecisionsPage";`
2. `ITEMS` 数组在 `{ key: "/track", label: "跟踪" }` 之后插入 `{ key: "/decisions", label: "决策" }`
3. `<Routes>` 内加 `<Route path="/decisions" element={<DecisionsPage />} />`

- [ ] **Step 6: 全量前端测试 + 构建**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 全部 vitest PASS;build 成功无类型错误

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/DecisionsPage.tsx frontend/src/pages/DecisionsPage.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): DecisionsPage with conclusion card + grouped role debate, add /decisions route"
```

---

### Task 6: 端到端验证(可选,需落库数据)

- [ ] **Step 1: 后端全量测试**

Run: `cd backend && .venv/bin/pytest -q`
Expected: 全绿(原有 + 新增 reasoning/详情端点测试)

- [ ] **Step 2: 起服务 curl 详情端点**(若库中已有 decisions 行)

Run: `curl -s --noproxy '*' http://localhost:8000/api/decisions/1 | head -c 400`
Expected: 返回含 `roles` 数组、`summary`、`action` 的 JSON;无 decisions 行时先跑 `run_decisions.py` 落库。

> 注:前端无浏览器无法可视化验证,靠 vitest + build + 该 curl 验证 API 契约。

---

## 备注

- 不改 `DecisionGraph` 与 `decisions` 表结构;解析器对历史 `reasoning`(多轮、缺 json、损坏 json)容错不抛错。
- `name` 暂返 null(YAGNI);后续若要股票名可从行情/名称源补,不阻塞本次。
- Dashboard 上原有的 `DecisionsPanel` 保留不动(新页独立);如需可在后续清理为只保留新页。
