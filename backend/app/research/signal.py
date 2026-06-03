from app.discovery.providers import SignalProvider
from app.discovery.snapshot import StockData
from app.research.store import ResearchStore


class ResearchSignalProvider(SignalProvider):
    def __init__(self, store: ResearchStore):
        self.store = store

    def compute(self, snapshot: dict[str, StockData]) -> dict[str, dict[str, float]]:
        sent: dict[str, float] = {}
        for code in snapshot:
            note = self.store.latest(code)
            if note is not None:
                sent[code] = note.sentiment
        return {"research_sent": sent}
