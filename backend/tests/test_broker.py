from datetime import date
import pytest
from app.db.models import Account
from app.data.prices import DictPriceProvider
from app.trading.broker import PaperBroker, InsufficientFunds, InsufficientShares


@pytest.fixture
def account(session):
    acc = Account(name="main", cash=100000.0)
    session.add(acc); session.commit()
    return acc


def test_buy_decrements_cash_and_creates_position(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "600519.SH", price=1000.0, shares=50, on=date(2026, 5, 29))
    session.refresh(account)
    assert account.cash == 50000.0
    pos = b.get_position(account.id, "600519.SH")
    assert pos.shares == 50 and pos.cost == 1000.0


def test_buy_averages_cost(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=100, on=date(2026, 5, 29))
    b.buy(account.id, "X", price=20.0, shares=100, on=date(2026, 5, 30))
    pos = b.get_position(account.id, "X")
    assert pos.shares == 200 and pos.cost == 15.0


def test_buy_insufficient_cash_rejected(session, account):
    b = PaperBroker(session)
    with pytest.raises(InsufficientFunds):
        b.buy(account.id, "X", price=1.0, shares=10**9, on=date(2026, 5, 29))


def test_sell_reduces_shares_and_adds_cash(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=100, on=date(2026, 5, 29))
    b.sell(account.id, "X", price=12.0, shares=60, on=date(2026, 5, 30))
    session.refresh(account)
    assert account.cash == 100000.0 - 1000.0 + 720.0
    assert b.get_position(account.id, "X").shares == 40


def test_sell_too_many_rejected(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=10, on=date(2026, 5, 29))
    with pytest.raises(InsufficientShares):
        b.sell(account.id, "X", price=10.0, shares=11, on=date(2026, 5, 30))


def test_mark_to_market_writes_snapshot(session, account):
    b = PaperBroker(session)
    b.buy(account.id, "X", price=10.0, shares=100, on=date(2026, 5, 29))   # cash 99000
    prices = DictPriceProvider({"X": 12.0})
    snap = b.mark_to_market(account.id, prices, on=date(2026, 5, 29))
    assert snap.cash == 99000.0
    assert snap.market_value == 1200.0
    assert snap.total == 100200.0
