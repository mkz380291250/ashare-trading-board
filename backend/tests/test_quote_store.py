from datetime import date
from app.data.quote_store import QuoteStore
from app.data.source import DailyBar


def _rows(d, close, factor):
    return [{"code": "X", "trade_date": d, "open": close, "high": close,
             "low": close, "close": close, "pre_close": close, "vol": 1000.0,
             "amount": 1.0, "adj_factor": factor, "turnover_rate": 0.5,
             "volume_ratio": 1.0, "circ_mv": 1.0, "total_mv": 1.0,
             "pe": 1.0, "pb": 1.0}]


def test_upsert_is_idempotent(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 10.0, 1.0))
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 11.0, 1.0))  # same PK
    bars = qs.get_bars("X", date(2026, 1, 1), date(2026, 1, 5))
    assert len(bars) == 1            # no duplicate row
    assert bars[0].close == 11.0     # last write wins


def test_mark_and_resume(session):
    qs = QuoteStore(session)
    assert qs.ingested_dates() == set()
    qs.mark_ingested(date(2026, 1, 2))
    qs.mark_ingested(date(2026, 1, 3))
    assert qs.ingested_dates() == {date(2026, 1, 2), date(2026, 1, 3)}


def test_get_bars_returns_sorted_dailybars(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 3), _rows(date(2026, 1, 3), 11.0, 2.0))
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 10.0, 1.0))
    bars = qs.get_bars("X", date(2026, 1, 1), date(2026, 1, 5))
    assert [b.trade_date for b in bars] == [date(2026, 1, 2), date(2026, 1, 3)]
    assert isinstance(bars[0], DailyBar)
    assert bars[0].adj_factor == 1.0 and bars[1].close == 11.0


def test_get_market_on(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 2), _rows(date(2026, 1, 2), 10.0, 1.0))
    rows = qs.get_market_on(date(2026, 1, 2))
    assert len(rows) == 1 and rows[0].code == "X"
