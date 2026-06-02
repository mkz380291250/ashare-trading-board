from datetime import date
from app.data.source import DailyBar
from app.data.adjust import to_hfq, to_qfq


def _bar(d, close, af):
    return DailyBar("X", d, close, close, close, close, 1000, af)


def test_hfq_multiplies_by_factor():
    bars = [_bar(date(2026, 1, 2), 10.0, 1.0), _bar(date(2026, 1, 3), 11.0, 2.0)]
    out = to_hfq(bars)
    assert out[0].close == 10.0
    assert out[1].close == 22.0           # 11 * 2.0
    assert out[1].volume == 1000          # volume untouched


def test_qfq_normalizes_to_latest_factor():
    bars = [_bar(date(2026, 1, 2), 10.0, 1.0), _bar(date(2026, 1, 3), 11.0, 2.0)]
    out = to_qfq(bars)
    # latest factor = 2.0 -> qfq = raw * af / 2
    assert out[0].close == 5.0            # 10 * 1 / 2
    assert out[1].close == 11.0           # 11 * 2 / 2
    assert out[1].open == 11.0


def test_empty_returns_empty():
    assert to_hfq([]) == []
    assert to_qfq([]) == []
