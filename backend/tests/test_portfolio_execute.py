from datetime import date
from types import SimpleNamespace
from app.db.models import Account, Position, Decision
from app.trading.broker import PaperBroker
from app.portfolio.execute import rebalance_portfolio


class _Brief:
    def __init__(self, code): self.code = code

def _brief_builder(codes):
    return [_Brief(c) for c in codes]

class _Graph:
    """按 code→action 脚本;缺省 HOLD。"""
    def __init__(self, actions=None): self.actions = actions or {}
    def run(self, brief):
        a = self.actions.get(brief.code, "HOLD")
        return SimpleNamespace(action=a, confidence=0.5, shares=0,
                               reasoning=f"{brief.code}:{a}")

def _ranked(n):
    return [(f"3000{i:02d}.SZ", i + 1) for i in range(n)]

def _seed_account(session, cash=1_000_000.0):
    session.add(Account(id=1, name="main", cash=cash)); session.commit()

def _equity_of(session, price):
    acc = session.get(Account, 1)
    mv = sum(p.shares * price for p in session.query(Position)
             .filter_by(account_id=1).all())
    return acc.cash + mv


def test_empty_holdings_buys_topk_equalweight(session):
    _seed_account(session)
    broker = PaperBroker(session)
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(),
        graph=_Graph(), broker=broker, brief_builder=_brief_builder,
        price_of=lambda c: 10.0, equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5, n_drop=15)
    assert len(res["bought"]) == 15
    positions = session.query(Position).filter_by(account_id=1).all()
    assert len(positions) == 15
    assert all(p.shares == 6600 for p in positions)          # 100万/15/10 整百
    assert res["sold"] == []


def test_buy_candidate_vetoed_by_sell_is_skipped(session):
    _seed_account(session)
    broker = PaperBroker(session)
    # rank0 的 300000 辩论 SELL → 跳过,由后备补位;最终仍买满 15
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(),
        graph=_Graph({"300000.SZ": "SELL"}), broker=broker,
        brief_builder=_brief_builder, price_of=lambda c: 10.0,
        equity_of=lambda: _equity_of(session, 10.0), topk=15, buffer=5,
        n_drop=15)
    assert "300000.SZ" in res["vetoed"]
    assert "300000.SZ" not in res["bought"]
    assert len(res["bought"]) == 15                          # 后备补满


def test_holding_vetoed_by_sell_is_sold(session):
    _seed_account(session, cash=900_000.0)
    broker = PaperBroker(session)
    broker.buy(1, "300000.SZ", 10.0, 6600, date(2026, 8, 10))  # 已持仓,rank1
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), {"300000.SZ"},
        graph=_Graph({"300000.SZ": "SELL"}), broker=broker,
        brief_builder=_brief_builder, price_of=lambda c: 10.0,
        equity_of=lambda: _equity_of(session, 10.0), topk=15, buffer=5,
        n_drop=15)
    assert "300000.SZ" in res["sold"]
    assert session.query(Position).filter_by(code="300000.SZ").first() is None


def test_risk_off_sells_only_no_buys(session):
    _seed_account(session, cash=900_000.0)
    broker = PaperBroker(session)
    broker.buy(1, "300021.SZ", 10.0, 6600, date(2026, 8, 10))   # rank22>20 → 应卖
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), {"300021.SZ"},
        graph=_Graph(), broker=broker, brief_builder=_brief_builder,
        price_of=lambda c: 10.0, equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5, n_drop=15, risk_off=True)
    assert res["bought"] == []                               # 停买
    assert "300021.SZ" in res["sold"]                        # TopkDropout 卖照旧


def test_decision_rows_persisted(session):
    _seed_account(session)
    broker = PaperBroker(session)
    rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(),
        graph=_Graph(), broker=broker, brief_builder=_brief_builder,
        price_of=lambda c: 10.0, equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5, n_drop=15)
    rows = session.query(Decision).filter_by(as_of=date(2026, 8, 17)).all()
    assert len(rows) >= 15
    assert {r.status for r in rows} <= {"EXECUTED", "VETOED", "CANDIDATE",
                                        "HELD", "SOLD"}
    assert sum(1 for r in rows if r.status == "EXECUTED") == 15


def test_veto_sell_bypasses_n_drop_cap(session):
    _seed_account(session, cash=700_000.0)
    broker = PaperBroker(session)
    # 5 只掉出榜(rank 22..26 >20)+ 1 只 rank1 但辩论 SELL
    dropped = [f"3000{i:02d}.SZ" for i in range(21, 26)]
    held_codes = dropped + ["300000.SZ"]
    for c in held_codes:
        broker.buy(1, c, 10.0, 6600, date(2026, 8, 10))
    res = rebalance_portfolio(
        session, date(2026, 8, 17), _ranked(30), set(held_codes),
        graph=_Graph({"300000.SZ": "SELL"}), broker=broker,
        brief_builder=_brief_builder, price_of=lambda c: 10.0,
        equity_of=lambda: _equity_of(session, 10.0),
        topk=15, buffer=5, n_drop=2)
    # 掉出榜5只里因排名最多卖2只 + 辩论SELL的300000额外卖 = 共3只
    assert len(res["sold"]) == 3
    assert "300000.SZ" in res["sold"]                    # 扫雷不受 n_drop 封顶
