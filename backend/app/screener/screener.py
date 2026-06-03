from dataclasses import dataclass
from datetime import date
from app.screener.themes import ThemeSource
from app.screener.earnings import EarningsSource, passes_earnings
from app.screener.filters import has_big_yang, not_at_top, day_pct


@dataclass(frozen=True)
class Pick:
    code: str
    theme: str
    as_of: date
    entry_close: float
    trigger: dict


class Screener:
    def __init__(self, themes: ThemeSource, earnings: EarningsSource, bars_provider):
        self.themes = themes
        self.earnings = earnings
        self.bars_provider = bars_provider  # code -> list[DailyBar] (ascending)

    def run(self, as_of: date) -> list[Pick]:
        picks: list[Pick] = []
        seen: set[str] = set()
        for theme in self.themes.themes():
            for code in self.themes.members(theme):
                if code in seen:
                    continue
                bars = self.bars_provider(code)
                if not bars or len(bars) < 2:
                    continue
                if not has_big_yang(bars, window=3, threshold=7.0):
                    continue
                if not not_at_top(bars):
                    continue
                e = self.earnings.latest(code)
                if not passes_earnings(e):
                    continue
                last, prev = bars[-1], bars[-2]
                picks.append(Pick(code=code, theme=theme, as_of=as_of,
                                  entry_close=last.close,
                                  trigger={"last_pct": round(day_pct(prev.close, last.close), 2),
                                           "np_yoy": e.np_yoy, "rev_yoy": e.rev_yoy}))
                seen.add(code)
        return picks
