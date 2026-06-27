"""冻结复合因子产物的读写。只存因子名(表达式从 FACTOR_LIBRARY 取),
权重现为等权,保留字段以备扩展。覆盖写时把旧产物归档到 archive/ 供回滚。"""
import json
import shutil
from dataclasses import dataclass, asdict, field
from pathlib import Path


@dataclass
class FrozenFactors:
    as_of: str
    factors: list[str]
    signs: dict[str, float]
    weights: dict[str, float]
    universe: str
    horizon: int
    source_report: str
    metrics_at_freeze: dict = field(default_factory=dict)


def load_frozen(path: str | Path) -> FrozenFactors:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"frozen factors not found at {p}")
    return FrozenFactors(**json.loads(p.read_text(encoding="utf-8")))


def save_frozen(ff: FrozenFactors, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = json.loads(p.read_text(encoding="utf-8"))
        archive = p.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, archive / f"frozen_composite_{old.get('as_of', 'unknown')}.json")
    p.write_text(json.dumps(asdict(ff), ensure_ascii=False, indent=2), encoding="utf-8")
