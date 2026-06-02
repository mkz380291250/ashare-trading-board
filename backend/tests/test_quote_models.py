from datetime import date
from app.db.models import DailyQuote, IngestedDay


def test_daily_quote_roundtrip(session):
    q = DailyQuote(code="600519.SH", trade_date=date(2026, 5, 29),
                   open=1270.0, high=1329.0, low=1270.0, close=1326.0,
                   pre_close=1275.98, vol=76478.0, amount=1.0e7, adj_factor=8.4464,
                   turnover_rate=0.6, volume_ratio=1.2, circ_mv=1.0e9,
                   total_mv=1.6e9, pe=30.0, pb=9.0)
    session.add(q); session.commit()
    got = session.get(DailyQuote, ("600519.SH", date(2026, 5, 29)))
    assert got.close == 1326.0 and got.adj_factor == 8.4464
    assert got.turnover_rate == 0.6


def test_ingested_day_pk(session):
    session.add(IngestedDay(trade_date=date(2026, 5, 29))); session.commit()
    assert session.get(IngestedDay, date(2026, 5, 29)) is not None
