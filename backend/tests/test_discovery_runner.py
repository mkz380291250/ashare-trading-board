import json
from datetime import date
from app.db.models import DiscoveryPick
from app.discovery.snapshot import StockData, MarketHistory
from app.discovery.providers import MomentumProvider
from app.discovery.scorer import DiscoveryScorer
from app.discovery.runner import DiscoveryRunner


class FakeHistory(MarketHistory):
    def load(self, as_of, window=20):
        def s(code, base):
            closes = [base + i for i in range(6)]
            vols = [100.0] * 5 + [100.0 + base]  # 量比 = (100+base)/100, distinct per code
            return StockData(code, closes, closes, vols, turnover=base)
        return {c: s(c, b) for c, b in [("A", 10), ("B", 20), ("C", 30)]}


def test_runner_persists_topn(session):
    runner = DiscoveryRunner(session, FakeHistory(), [MomentumProvider()],
                             DiscoveryScorer(top_n=2))
    picks = runner.run(date(2026, 5, 29))
    assert len(picks) == 2
    rows = session.query(DiscoveryPick).order_by(DiscoveryPick.rank).all()
    assert len(rows) == 2
    assert rows[0].rank == 1 and rows[1].rank == 2
    assert rows[0].score >= rows[1].score
    assert "mom_5d" in json.loads(rows[0].factors)


def test_runner_is_idempotent_per_date(session):
    runner = DiscoveryRunner(session, FakeHistory(), [MomentumProvider()],
                             DiscoveryScorer(top_n=2))
    runner.run(date(2026, 5, 29))
    runner.run(date(2026, 5, 29))  # rerun same date
    assert session.query(DiscoveryPick).count() == 2  # not 4
