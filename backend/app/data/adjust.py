from dataclasses import replace
from app.data.source import DailyBar


def _scale(bar: DailyBar, k: float) -> DailyBar:
    return replace(bar, open=bar.open*k, high=bar.high*k,
                   low=bar.low*k, close=bar.close*k)  # volume untouched


def to_hfq(bars: list[DailyBar]) -> list[DailyBar]:
    return [_scale(b, b.adj_factor) for b in bars]


def to_qfq(bars: list[DailyBar]) -> list[DailyBar]:
    if not bars:
        return []
    latest = bars[-1].adj_factor
    return [_scale(b, b.adj_factor / latest) for b in bars]
