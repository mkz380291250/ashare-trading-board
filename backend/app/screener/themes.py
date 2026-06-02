import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable

_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}


def datacenter_board_members(board: str, tries: int = 4) -> list[str]:
    """Fetch member SECUCODEs (e.g. '000034.SZ') of one EastMoney concept board.

    Uses datacenter-web (plain JSON, no anti-bot) instead of the blocked push2
    endpoint, so it sidesteps tushare's ths_member/ths_index rate limits.
    Board name must match EastMoney exactly (server-side `like` filtering is
    unsupported). Returns [] on persistent failure rather than raising.
    """
    import requests

    params = {
        "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
        "columns": "SECUCODE,BOARD_NAME",
        "filter": f'(BOARD_NAME="{board}")',
        "pageNumber": 1,
        "pageSize": 600,
    }
    for _ in range(tries):
        try:
            r = requests.get(_DATACENTER, params=params, headers=_HDR, timeout=20)
            data = (r.json().get("result") or {}).get("data") or []
            return [x["SECUCODE"] for x in data]
        except Exception:
            time.sleep(1.5)
    return []


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


class EastMoneyThemeSource(ThemeSource):
    """theme -> EastMoney concept board names -> union of member codes.

    Each theme maps to one or more exact EastMoney board names; members come
    from the datacenter API (see ``datacenter_board_members``). When ``valid``
    is given, results are intersected with it (e.g. codes present in the quote
    DB) so unknown/delisted tickers are dropped.
    """

    def __init__(
        self,
        boards_by_theme: dict[str, list[str]],
        fetch_board: Callable[[str], list[str]] = datacenter_board_members,
        valid: Iterable[str] | None = None,
    ):
        self._boards = boards_by_theme
        self._fetch = fetch_board
        self._valid = set(valid) if valid is not None else None

    def themes(self) -> list[str]:
        return list(self._boards.keys())

    def members(self, theme: str) -> list[str]:
        codes: set[str] = set()
        for board in self._boards.get(theme, []):
            codes.update(self._fetch(board))
        if self._valid is not None:
            codes &= self._valid
        return sorted(codes)
