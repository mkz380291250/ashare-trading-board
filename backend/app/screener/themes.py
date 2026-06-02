from abc import ABC, abstractmethod


class ThemeSource(ABC):
    @abstractmethod
    def themes(self) -> list[str]: ...
    @abstractmethod
    def members(self, theme: str) -> list[str]: ...


class StaticThemeSource(ThemeSource):
    """Curated theme -> codes (fallback when tushare concept API is gated)."""

    def __init__(self, mapping: dict[str, list[str]]):
        self._m = mapping

    def themes(self) -> list[str]:
        return list(self._m.keys())

    def members(self, theme: str) -> list[str]:
        return list(self._m.get(theme, []))


class TushareThemeSource(ThemeSource):
    """theme -> concept index code -> member stock codes via ths_member."""

    def __init__(self, pro, index_by_theme: dict[str, str]):
        self.pro = pro
        self._idx = index_by_theme

    def themes(self) -> list[str]:
        return list(self._idx.keys())

    def members(self, theme: str) -> list[str]:
        code = self._idx.get(theme)
        if not code:
            return []
        df = self.pro.ths_member(ts_code=code)
        return [str(x) for x in df["con_code"].tolist()]
