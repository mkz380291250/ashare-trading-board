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
