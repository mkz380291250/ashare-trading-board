"""baostock 日线源(免费、无积分),对齐 TushareSource 的 DailyBar 输出:
- 价格用 adjustflag=3(不复权)+ backAdjustFactor 做 adj_factor,与 tushare 同为
  "原始价 + 后复权累计因子"的口径;因子绝对值与 tushare 不同(基准日不同),但同一
  股票内的比值一致,复权后价格序列可对上。
- baostock volume 单位是"股",tushare vol 是"手",这里统一转成手。
- 停牌日 baostock 会返回空价格行(tradestatus=0),tushare daily 不返回,这里丢掉。
"""
from datetime import date
import pandas as pd
from app.data.source import DailyBar, MarketDataSource

_FIELDS = "date,code,open,high,low,close,volume,tradestatus"


def to_bs_code(ts_code: str) -> str:
    """600519.SH -> sh.600519"""
    sym, ex = ts_code.split(".")
    return f"{ex.lower()}.{sym}"


def to_ts_code(bs_code: str) -> str:
    """sh.600519 -> 600519.SH"""
    ex, sym = bs_code.split(".")
    return f"{sym}.{ex.upper()}"


def _fmt(d: date) -> str:
    return d.isoformat()


def _parse(s: str) -> date:
    return date.fromisoformat(s)


class BaostockSource(MarketDataSource):
    def __init__(self, bs=None):
        if bs is None:
            import baostock
            bs = baostock
        self.bs = bs
        self._logged_in = False

    def _ensure_login(self, timeout: float | None = 120.0):
        if not self._logged_in:
            rs = self.bs.login()
            if rs.error_code != "0":
                raise RuntimeError(f"baostock login failed: {rs.error_msg}")
            self._logged_in = True
            if timeout:
                # baostock 的 socket 默认无超时,服务端卡住(每日 17:30~18:30 更新
                # 时段常见)会永久挂死;这里给它设个超时让上层能重试/切源
                try:
                    from baostock.common import context
                    context.default_socket.settimeout(timeout)
                except Exception:      # noqa: BLE001 — 假 bs 模块/内部结构变化
                    pass

    def close(self):
        if self._logged_in:
            self.bs.logout()
            self._logged_in = False

    @staticmethod
    def _query(rs) -> pd.DataFrame:
        if rs is None or rs.error_code != "0":
            raise RuntimeError(f"baostock query failed: {getattr(rs, 'error_msg', rs)}")
        # 不用 rs.get_data():它翻页时调 DataFrame.append(pandas 2 已删),
        # 结果超过一页(10 年日线)就崩;自己按行翻页拼。
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return pd.DataFrame(rows, columns=rs.fields)

    def get_daily_bars(self, code: str, start: date, end: date) -> list[DailyBar]:
        self._ensure_login()
        bs_code = to_bs_code(code)
        k = self._query(self.bs.query_history_k_data_plus(
            bs_code, _FIELDS, start_date=_fmt(start), end_date=_fmt(end),
            frequency="d", adjustflag="3"))
        if k.empty:
            return []
        k = k[k["tradestatus"] == "1"].copy()
        k = k[k["close"] != ""]
        # 因子是按除权日的阶梯函数;查全历史再 asof 到每个交易日
        adj = self._query(self.bs.query_adjust_factor(bs_code, "1990-01-01", _fmt(end)))
        k["_d"] = pd.to_datetime(k["date"])
        k = k.sort_values("_d")
        if adj.empty:
            k["adj_factor"] = 1.0
        else:
            adj["_d"] = pd.to_datetime(adj["dividOperateDate"])
            adj = adj.sort_values("_d")
            adj["f"] = adj["backAdjustFactor"].astype(float)
            k = pd.merge_asof(k, adj[["_d", "f"]], on="_d", direction="backward")
            # 首次除权日之前:用最早一档因子(baostock 该段与首档一致)
            k["adj_factor"] = k["f"].fillna(adj["f"].iloc[0])
        bars: list[DailyBar] = []
        for _, r in k.iterrows():
            bars.append(DailyBar(
                code=code, trade_date=_parse(r["date"]),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                volume=float(r["volume"]) / 100.0,   # 股 → 手
                adj_factor=float(r["adj_factor"]),
            ))
        return bars

    def trading_days(self, start: date, end: date) -> list[date]:
        self._ensure_login()
        df = self._query(self.bs.query_trade_dates(start_date=_fmt(start), end_date=_fmt(end)))
        if df.empty:
            return []
        return sorted(_parse(d) for d in df[df["is_trading_day"] == "1"]["calendar_date"])

    def index_daily(self, bs_code: str, start: date, end: date) -> pd.DataFrame:
        """指数日线(如 sh.000300)→ 列 date/open/high/low/close/volume(手),升序。"""
        self._ensure_login()
        df = self._query(self.bs.query_history_k_data_plus(
            bs_code, "date,open,high,low,close,volume",
            start_date=_fmt(start), end_date=_fmt(end), frequency="d"))
        if df.empty:
            return df
        df = df[df["close"] != ""].copy()
        for c in ("open", "high", "low", "close", "volume"):
            df[c] = df[c].astype(float)
        df["volume"] = df["volume"] / 100.0
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)


def stock_basic(src: "BaostockSource | None" = None) -> list[tuple[str, str, "date | None"]]:
    """在市 A 股(沪深主板/创业板/科创板)基础信息 -> [(ts_code, name, list_date)]。
    替代 tushare stock_basic(list_status=L);baostock 无北交所。"""
    own = src is None
    src = src or BaostockSource()
    try:
        src._ensure_login()
        df = src._query(src.bs.query_stock_basic())
    finally:
        if own:
            src.close()
    out = []
    for r in df.itertuples(index=False):
        if r.type != "1" or r.status != "1":          # 1=股票 & 上市中
            continue
        ex, sym = r.code.split(".")
        if not ((ex == "sh" and sym[:2] in ("60", "68")) or (ex == "sz" and sym[:2] in ("00", "30"))):
            continue
        try:
            ld = date.fromisoformat(r.ipoDate)
        except (ValueError, TypeError):
            ld = None
        out.append((to_ts_code(r.code), r.code_name, ld))
    return out
