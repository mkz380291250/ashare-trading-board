import json
from datetime import date
from sqlalchemy import delete
from sqlalchemy.orm import Session
from app.db.models import DiscoveryPick
from app.discovery.snapshot import MarketHistory
from app.discovery.providers import SignalProvider
from app.discovery.scorer import DiscoveryScorer


class DiscoveryRunner:
    def __init__(self, session: Session, history: MarketHistory,
                 providers: list[SignalProvider], scorer: DiscoveryScorer,
                 window: int = 20):
        self.s = session
        self.history = history
        self.providers = providers
        self.scorer = scorer
        self.window = window

    def run(self, as_of: date):
        snapshot = self.history.load(as_of, self.window)
        factors: dict[str, dict[str, float]] = {}
        for p in self.providers:
            for name, fmap in p.compute(snapshot).items():
                factors[name] = fmap
        picks = self.scorer.score(factors)
        self.s.execute(delete(DiscoveryPick).where(DiscoveryPick.as_of == as_of))
        for i, (code, total, raw) in enumerate(picks, 1):
            self.s.add(DiscoveryPick(as_of=as_of, code=code, rank=i,
                                     score=total, factors=json.dumps(raw)))
        self.s.commit()
        return picks
