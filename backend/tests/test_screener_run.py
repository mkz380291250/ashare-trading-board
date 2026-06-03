from datetime import date, timedelta
from app.data.source import DailyBar
from app.screener.themes import StaticThemeSource
from app.screener.earnings import Earnings, EarningsSource
from app.screener.screener import Screener

D0 = date(2026, 1, 1)


def _good_bars():
    """52w high ~20 early, then a low calm base ~10, then a >7% green candle to
    10.9 — qualifies big-yang AND not-at-top (10.9 <= 0.85*20)."""
    bars = []
    for i in range(30):          # high base -> establishes 52w high = 20
        bars.append(DailyBar("PASS.SH", D0 + timedelta(days=i), 20, 20, 20, 20.0, 1000, 1.0))
    for i in range(30, 59):      # calm low base at 10
        bars.append(DailyBar("PASS.SH", D0 + timedelta(days=i), 10, 10.2, 9.8, 10.0, 1000, 1.0))
    # last day: big yang from prev close 10 -> 10.9 (+9%), green
    bars.append(DailyBar("PASS.SH", D0 + timedelta(days=59), 10.1, 10.95, 10.0, 10.9, 1000, 1.0))
    return bars


class FakeEarnings(EarningsSource):
    def latest(self, code):
        return Earnings(np_yoy=25.0, rev_yoy=5.0)


def test_screener_selects_qualifying_stock():
    themes = StaticThemeSource({"算力": ["PASS.SH"]})
    bars = {"PASS.SH": _good_bars()}
    sc = Screener(themes=themes, earnings=FakeEarnings(),
                  bars_provider=lambda code: bars[code])
    picks = sc.run(as_of=_good_bars()[-1].trade_date)
    assert len(picks) == 1
    p = picks[0]
    assert p.code == "PASS.SH" and p.theme == "算力"
    assert p.entry_close == 10.9


def test_screener_rejects_weak_earnings():
    class Weak(EarningsSource):
        def latest(self, code): return Earnings(np_yoy=5.0, rev_yoy=1.0)
    themes = StaticThemeSource({"算力": ["PASS.SH"]})
    bars = {"PASS.SH": _good_bars()}
    sc = Screener(themes=themes, earnings=Weak(), bars_provider=lambda c: bars[c])
    assert sc.run(as_of=_good_bars()[-1].trade_date) == []
