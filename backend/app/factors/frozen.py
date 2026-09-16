"""冻结复合因子产物的读写。只存因子名(表达式从 FACTOR_LIBRARY 取),
权重等权或按 IR 加权(composite_score 会用)。覆盖写时把旧产物归档到 archive/ 供回滚。"""
import json
import shutil
from dataclasses import dataclass, asdict, field
from pathlib import Path

import pandas as pd
from app.quant.factor_compose import (dedup_by_correlation, dedup_by_family,
                                      ir_weights, sign_correct)


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


def select_frozen(ranked: list[str], rank_ic: dict[str, float], corr: pd.DataFrame,
                  *, universe: str, horizon: int, source_report: str, as_of: str,
                  metrics: dict, threshold: float = 0.8, family: dict | None = None,
                  family_cap: int = 2, ir_map: dict | None = None) -> FrozenFactors:
    """按重要性降序的 ranked + 相关矩阵 corr 去重(family 给了则同族限量 family_cap),
    符号由 rank_ic 方向定;ir_map 给了则按 |IR| 截断加权,否则等权。"""
    if family:
        kept = dedup_by_family(ranked, corr, family, threshold=threshold, family_cap=family_cap)
    else:
        kept = dedup_by_correlation(ranked, corr, threshold=threshold)
    signs = {f: sign_correct(rank_ic[f]) for f in kept}
    if ir_map:
        weights = ir_weights(kept, ir_map)
    else:
        w = round(1.0 / len(kept), 6) if kept else 0.0
        weights = {f: w for f in kept}
    return FrozenFactors(as_of=as_of, factors=kept, signs=signs, weights=weights,
                         universe=universe, horizon=horizon,
                         source_report=source_report, metrics_at_freeze=metrics)
