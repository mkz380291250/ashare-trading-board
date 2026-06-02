from datetime import date, timedelta
from app.data.source import DailyBar
from app.screener.filters import has_big_yang, not_at_top, forward_return

D0 = date(2026, 1, 1)


def _bar(d, o, c, h=None, l=None):
    return DailyBar("X", d, o, h or max(o, c), l or min(o, c), c, 1000, 1.0)


def test_big_yang_detects_gt7pct_green_in_window():
    bars = [_bar(date(2026, 1, 1), 10, 10.0), _bar(date(2026, 1, 2), 10, 10.1),
            _bar(date(2026, 1, 5), 10.1, 10.9)]  # 10.1 -> 10.9 = +7.92%, green
    assert has_big_yang(bars, window=3, threshold=7.0) is True


def test_big_yang_exactly_7pct_fails():
    bars = [_bar(date(2026, 1, 1), 10, 10.0), _bar(date(2026, 1, 2), 10, 10.7)]  # +7.0%
    assert has_big_yang(bars, window=3, threshold=7.0) is False  # strictly >7


def test_big_yang_red_candle_excluded():
    # +8% on close vs prev close but close<open (gap up then fade) -> not green
    bars = [_bar(date(2026, 1, 1), 10, 10.0), _bar(date(2026, 1, 2), 11.0, 10.8)]
    assert has_big_yang(bars, window=3, threshold=7.0) is False


def test_big_yang_outside_window_excluded():
    bars = [_bar(date(2026, 1, 1), 10, 11.0),  # +10% but 3 days before the last
            _bar(date(2026, 1, 2), 11, 11.0), _bar(date(2026, 1, 5), 11, 11.0),
            _bar(date(2026, 1, 6), 11, 11.0)]
    assert has_big_yang(bars, window=3, threshold=7.0) is False


def test_not_at_top_true_when_below_high_and_calm():
    bars = [_bar(D0 + timedelta(days=i), 100, 100.0, h=100) for i in range(60)]
    bars += [_bar(D0 + timedelta(days=70), 85, 85.0, h=85)]
    assert not_at_top(bars, high_frac=0.85, max_ret=0.5) is True


def test_not_at_top_false_when_near_high():
    bars = [_bar(D0 + timedelta(days=i), 100, 100.0, h=100) for i in range(60)]
    bars += [_bar(D0 + timedelta(days=70), 95, 95.0, h=95)]  # 95 > 0.85*100
    assert not_at_top(bars, high_frac=0.85, max_ret=0.5) is False


def test_not_at_top_false_when_60d_return_too_high():
    # 60 bars total so bars[-60] == bars[0] (=10); last close 16 -> +60% over the window
    bars = [_bar(D0, 10, 10.0, h=10)]
    bars += [_bar(D0 + timedelta(days=i + 1), 16, 16.0, h=100) for i in range(59)]
    assert not_at_top(bars, high_frac=0.85, max_ret=0.5) is False


def test_forward_return():
    assert abs(forward_return(10.0, 12.0) - 0.2) < 1e-9
    assert forward_return(10.0, None) is None
