from datetime import date


class ResearchRunner:
    def __init__(self, source, analyzer, store):
        self.source = source
        self.analyzer = analyzer
        self.store = store

    def run(self, universe: set[str], as_of: date) -> int:
        n = 0
        for code in sorted(universe):
            try:
                items = self.source.fetch(code, as_of)
                note = self.analyzer.analyze(code, items)
                src = getattr(items[0], "source", "none") if items else "none"
                self.store.upsert(code, as_of, note, src)
                n += 1
            except Exception as e:  # 单只失败不阻断其余,但留痕便于排查
                print(f"SKIP {code}: {type(e).__name__}: {e}", flush=True)
                continue
        return n
