from datetime import date
from app.data.quote_store import QuoteStore
from app.discovery.snapshot import QuoteStoreMarketHistory


def _row(code, d, close, high, turnover=1.0, vol_ratio=1.0):
    return {"code": code, "trade_date": d, "open": close, "high": high,
            "low": close, "close": close, "pre_close": close, "vol": 100.0,
            "amount": 1.0, "adj_factor": 1.0, "turnover_rate": turnover,
            "volume_ratio": vol_ratio, "circ_mv": 1.0, "total_mv": 1.0,
            "pe": 1.0, "pb": 1.0}


def test_history_builds_per_code_window(session):
    qs = QuoteStore(session)
    for i, d in enumerate([date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 6)]):
        qs.upsert_day(d, [_row("A", d, 10.0 + i, 11.0 + i, turnover=2.0, vol_ratio=1.5)])
    hist = QuoteStoreMarketHistory(qs).load(date(2026, 1, 6), window=20)
    a = hist["A"]
    assert a.closes == [10.0, 11.0, 12.0]   # ascending up to as_of
    assert a.highs == [11.0, 12.0, 13.0]
    assert a.volumes == [100.0, 100.0, 100.0]  # from r.vol
    assert a.turnover == 2.0                    # turnover_rate from the as_of row


def test_history_only_includes_codes_present_on_as_of(session):
    qs = QuoteStore(session)
    qs.upsert_day(date(2026, 1, 2), [_row("B", date(2026, 1, 2), 5.0, 5.0)])  # not on as_of
    qs.upsert_day(date(2026, 1, 6), [_row("A", date(2026, 1, 6), 9.0, 9.0)])
    hist = QuoteStoreMarketHistory(qs).load(date(2026, 1, 6), window=20)
    assert set(hist.keys()) == {"A"}
