# Slice 3: Multi-Agent Decision Engine — Design Spec

Date: 2026-06-02. Builds on slice 0+1 (paper broker), historical DB, and slice 2
(discovery Top-8). Weekly cadence.

## Goal

A weekly **multi-agent decision engine** that, for the current holdings plus the
discovery engine's Top-8 candidates, runs a TradingAgents-style debate (analysts →
bull/bear researchers → trader → risk committee) and produces a **BUY/SELL/HOLD**
recommendation per stock with full reasoning. Recommendations are **PENDING** until
the user approves them in the UI, on approval the **PaperBroker** executes the trade
(人机协同).

## Decisions (locked)

- **Kernel:** reference TradingAgents-CN (`hsliuping/TradingAgents-CN`) agent roles
  and debate flow; **port the prompts/flow onto our stack** — no langgraph, akshare,
  MongoDB, redis, or its web app. The CN fork requires py>=3.10 (compatible) but its
  full dependency tree is too heavy/conflicting, so we vendor ideas, not the package.
- **Decision target:** current holdings ∪ discovery Top-8.
- **Agent roles:** the full set (data-permitting).
- **LLM:** pluggable `LLMClient`; **default `LocalClaudeClient`** (headless
  `claude -p`), alternative `DeepSeekClient` (OpenAI-compatible API).
- **Cadence:** weekly.
- **财报 vs 研报:** structured financials (净利/营收 YoY via tushare `fina_indicator`,
  PE/PB from the quote DB) are **in** slice 3. Broker research-report text (研报)
  needs scraping → **slice 4**; slice 3 keeps the news/research analyst role as an
  interface stub fed empty for now.

## Architecture

New module `backend/app/decision/`, parallel to `discovery/`/`trading/`.

### LLM client (pluggable)

- **`LLMClient`** (ABC) — `complete(prompt: str, system: str | None) -> str`.
- **`LocalClaudeClient`** (default) — runs `claude -p <prompt>` as a subprocess
  (`--output-format text`), returns stdout. Configurable binary path + timeout.
- **`DeepSeekClient`** — POSTs the OpenAI-compatible chat-completions endpoint
  (`DEEPSEEK_BASE_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`).
- Selected by config (`DECISION_LLM=local|deepseek`, default `local`).

### Agents (ported prompts, our orchestration)

Each agent is a thin object: build a prompt from the stock brief (+ upstream agent
outputs), call the `LLMClient`, return a report. Roles:

1. **Analysts** — `PriceVolumeAnalyst` (量价: trend + the 4 discovery factors),
   `FundamentalAnalyst` (财报: net-profit/revenue YoY, PE/PB). `NewsAnalyst` /
   `ResearchAnalyst` exist as roles but receive empty context until slice 4.
2. **Researchers** — `BullResearcher` vs `BearResearcher` debate over N rounds
   (default 2), each seeing the analysts' reports and the other's last argument.
3. **Trader** — `Trader` synthesizes analysts + debate into a draft BUY/SELL/HOLD.
4. **Risk committee** — `AggressiveDebater`, `ConservativeDebater`, `NeutralDebater`
   argue, then `RiskManager` issues the final verdict.

### Structured output

Every agent's free-text report must **end with a fenced JSON verdict** the
orchestrator parses, e.g. `{"stance": "bull", "confidence": 0.7}` for researchers,
`{"action": "BUY", "confidence": 0.6, "shares": 100}` for trader/risk manager. A
`parse_verdict(text) -> dict` helper extracts the last JSON block; missing/invalid
→ a safe default (HOLD, confidence 0).

### Orchestration

- **`DecisionGraph.run(brief) -> Decision`** — analysts → bull/bear debate →
  trader → risk debate → risk manager. Accumulates each agent's report into a
  combined markdown `reasoning`. Returns `(action, confidence, shares, reasoning)`.
- **`DecisionRunner`** — for each target code: assemble brief (from QuoteStore +
  discovery factors + tushare fundamentals + holding), run `DecisionGraph`, upsert a
  PENDING `decisions` row. Idempotent per (as_of, code).

### Data flow

```
holdings ∪ discovery Top-8
  -> StockBrief (QuoteStore bars + discovery factors + fina_indicator + holding)
  -> DecisionGraph: analysts -> bull/bear -> trader -> risk -> RiskManager
       (each agent -> LLMClient -> report; verdicts parsed)
  -> decisions row (PENDING, action/confidence/shares/reasoning-md)
  -> GET /api/decisions -> 决策 panel -> approve -> PaperBroker trade
```

## Data model

New table **`decisions`** (PK id; unique (as_of, code)):

- `as_of` (date, the decision week), `code` (str16)
- `action` (str: BUY/SELL/HOLD), `confidence` (float), `shares` (int, suggested)
- `reasoning` (str, markdown of the full debate)
- `status` (str: PENDING/APPROVED/REJECTED, default PENDING)
- `created_at` (date)

## API

- **`GET /api/decisions`** — latest week's decisions (or `?date=`), with status.
- **`POST /api/decisions/{id}/approve`** — APPROVED + execute via PaperBroker
  (BUY/SELL at latest close; HOLD just marks approved). Idempotent (no double-exec).
- **`POST /api/decisions/{id}/reject`** — REJECTED, no trade.

## Runner

- **`scripts/run_decisions.py`** — weekly: target = holdings ∪ latest discovery
  Top-8; run `DecisionRunner`; print a summary. Uses the configured LLM (default
  local Claude). Verified by a real small-sample run.

## Frontend

- A **决策** tab/panel: rows per stock — action, confidence, status; expandable to
  the markdown `reasoning`; Approve / Reject buttons calling the API. Reuses `apiGet`
  / `apiPost`; reasoning rendered as markdown.

## Testing strategy (TDD)

- **Pure logic (unit, fake LLMClient returning canned reports):**
  - `parse_verdict` (extracts last JSON; bad input → HOLD/0).
  - brief assembly (QuoteStore + factors + fundamentals + holding → StockBrief).
  - `DecisionGraph` flow with a `FakeLLMClient` (deterministic per-role replies) →
    asserts final action/confidence and that reasoning contains each role's text.
  - `DecisionRunner` persistence + idempotency per (as_of, code).
- **LLMClient impls:** `LocalClaudeClient` (subprocess) and `DeepSeekClient` (HTTP)
  behind the interface, mocked in unit tests; one real smoke test for local Claude.
- **API:** approve → PaperBroker trade, reject → no trade, over an in-memory DB.
- **Integration:** a real 1–2 stock run end-to-end with local Claude (not a unit test).

## Configuration

- `DECISION_LLM` (default `local`), `CLAUDE_BIN` (default `/usr/local/bin/claude`),
  debate rounds (default 2), risk committee on/off. DeepSeek vars reuse existing
  `.env` keys.

## Risks

- **Local Claude latency:** full role set × many stocks × `claude -p` is slow and
  serial. Mitigations: small target set (holdings + 8), cache per (as_of, code),
  allow `DECISION_LLM=deepseek` for fast batch. The LLMClient interface makes the
  swap trivial.
- **LLM output drift:** enforced JSON verdict + `parse_verdict` fallback to HOLD.
- **News/research analysts** are stubs until slice 4 wires scraped 研报.

## Constraints honored

- Reuse TradingAgents-CN agent design (ported), not its heavy package.
- Weekly cadence; human-in-the-loop approval before any paper trade.
- Pluggable LLM (local Claude default) and pluggable analyst roles (slice-4 ready).
- External data isolated behind interfaces; pure logic TDD-first.
