"""全市场日线增量采集(替代 tushare MarketFetcher,2026-09 tushare 到期):
- 沪深股票走 baostock(逐只查 K 线;单连接顺序查,baostock 服务端对并发不友好)。
  socket 设超时 + 连续失败熔断:baostock 卡死/宕机时剩余股票自动切腾讯兜底。
- 北交所(.BJ)baostock 不覆盖,走腾讯日线(raw + hfq)。
- 复权因子:各源的绝对刻度与库里 tushare 的不同,按每只股票"库内最后一行"的
  因子做等比换算(scale = 库因子 / 源因子,同一天),保证 qlib 历史序列连续。
  无除权(preclose == 前一收盘)时直接沿用库内因子,省掉一次 adj 查询。
- 流通市值 = close × volume / turn(与 tushare circ_mv 一致到 1e-4);总市值按库内
  最后一行的 总/流通 比例外推;量比 = vol / 前5日均量。
- 单位对齐 tushare:vol 手、amount 千元、mv 万元、turnover %。pe 用 peTTM
  (tushare 的 pe 是静态市盈率,仅辩论 brief 展示用,口径差异可接受)。
"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.data.baostock_source import BaostockSource, to_bs_code
from app.data import tencent_daily as tx

K_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,peTTM,pbMRQ"
LOOKBACK_DAYS = 14          # 从库内最后一行往前多拉的自然日(供量比用前5个交易日)
MAX_FAIL_RATIO = 0.02       # 两个源都失败的比例超过这个值视为源故障,整轮抛错不落库
BREAKER_FAILS = 3           # baostock 连续失败这么多只 → 熔断,剩余全走腾讯
@dataclass(frozen=True)
class RefRow:
    """某只股票在库内的最后一行,用于因子换算 / 市值外推 / 判定哪些日期是新的。"""
    trade_date: date
    close: float
    adj_factor: float
    circ_mv: float | None
    total_mv: float | None
    pe: float | None = None
    pb: float | None = None
    vols5: tuple = ()          # 库内最近 5 个交易日成交量(手),供量比


def is_bj(code: str) -> bool:
    return code.endswith(".BJ")


def _f(v, scale: float = 1.0) -> float | None:
    if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
        return None
    return float(v) * scale


def _volume_ratio(vols: list[float], i: int) -> float | None:
    if i < 5:
        return None
    prev = vols[i - 5:i]
    avg = sum(prev) / 5
    return round(vols[i] / avg, 2) if avg > 0 else None


def _pick_pb(q_pb, ref: RefRow | None, close: float):
    """pb:腾讯快照与 tushare/baostock 口径一致的占 95%+,个别股(如 603333)差 30%;
    以库内 pb 按价格比例外推为基准,快照值偏差 ≤5% 才采用(吸收新财报更新),否则用外推。"""
    scaled = ref.pb * close / ref.close if (ref and ref.pb and ref.close) else None
    if q_pb is not None and (scaled is None or abs(q_pb / scaled - 1) <= 0.05):
        return q_pb
    return scaled


def needs_adj_query(k: pd.DataFrame, ref: RefRow | None) -> bool:
    """新日期里有除权(preclose ≠ 前一交易日收盘)或没有可对齐的库内参考行 → 要查因子。"""
    if ref is None:
        return True
    dates = k["date"].tolist()
    if ref.trade_date.isoformat() not in dates:
        return True
    closes = [float(x) for x in k["close"]]
    pres = [float(x) if x != "" else None for x in k["preclose"]]
    for i, d in enumerate(dates):
        if date.fromisoformat(d) <= ref.trade_date:
            continue
        if i == 0 or pres[i] is None or abs(pres[i] - closes[i - 1]) > 0.0051:
            return True
    return False


def rows_from_baostock(code: str, k: pd.DataFrame, adj: pd.DataFrame | None,
                       ref: RefRow | None) -> list[dict]:
    """baostock K 线(adjustflag=3 原始价)→ daily_quotes 行(只含 ref 之后的新日期)。
    adj 为 None 表示无除权,因子沿用 ref.adj_factor。"""
    if k is None or k.empty:
        return []
    k = k[(k["tradestatus"] == "1") & (k["close"] != "")].copy()
    if k.empty:
        return []
    k["_d"] = pd.to_datetime(k["date"])
    k = k.sort_values("_d").reset_index(drop=True)
    if adj is not None and not adj.empty:
        a = adj.copy()
        a["_d"] = pd.to_datetime(a["dividOperateDate"])
        a = a.sort_values("_d")
        a["f"] = a["backAdjustFactor"].astype(float)
        k = pd.merge_asof(k, a[["_d", "f"]], on="_d", direction="backward")
        k["f"] = k["f"].fillna(a["f"].iloc[0])
    else:
        k["f"] = 1.0 if ref is None else ref.adj_factor

    scale = 1.0
    if ref is not None and adj is not None:
        hit = k[k["date"] == ref.trade_date.isoformat()]
        if not hit.empty and float(hit["f"].iloc[0]) > 0:
            scale = ref.adj_factor / float(hit["f"].iloc[0])

    vols = [float(v) / 100.0 for v in k["volume"]]          # 股 → 手
    mv_ratio = (ref.total_mv / ref.circ_mv
                if ref and ref.circ_mv and ref.total_mv else None)
    ref_circ_shares = (ref.circ_mv * 1e4 / ref.close
                       if ref and ref.circ_mv and ref.close else None)
    rows: list[dict] = []
    for i, r in k.iterrows():
        d = date.fromisoformat(r["date"])
        if ref is not None and d <= ref.trade_date:
            continue
        close = float(r["close"])
        turn = _f(r["turn"])
        if turn and vols[i] > 0:
            circ_mv = close * vols[i] * 100.0 / (turn / 100.0) / 1e4
        elif ref_circ_shares:
            circ_mv = close * ref_circ_shares / 1e4
        else:
            circ_mv = None
        rows.append({
            "code": code, "trade_date": d,
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": close,
            "pre_close": _f(r["preclose"]), "vol": vols[i],
            "amount": _f(r["amount"], 1e-3),                  # 元 → 千元
            "adj_factor": float(r["f"]) * scale,
            "turnover_rate": turn,
            "volume_ratio": _volume_ratio(vols, i),
            "circ_mv": circ_mv,
            "total_mv": circ_mv * mv_ratio if (circ_mv and mv_ratio) else None,
            "pe": _f(r["peTTM"]), "pb": _f(r["pbMRQ"]),
        })
    return rows


# ── 腾讯日线(北交所 + 沪深兜底)─────────────────────────────────────────
def rows_from_tencent(code: str, raw: list[list], hfq: list[list], ref: RefRow | None,
                      quote: dict | None = None, max_date: date | None = None) -> list[dict]:
    """腾讯 fqkline 行 [date, open, close, high, low, vol(手), {除权}?]。
    因子:以 ref 因子为起点,只在 (hfq/raw) 比值跳变(除权)的日期按比值更新;
    无 ref 时从 1.0 起。换手/流通市值按流通股本(库内 ref 推算,精度高于腾讯 2 位小数)
    计算;quote(仅当其日期等于该行日期)补成交额/pe/pb,其余日期 pe/pb 按价格比例
    外推、成交额留空。max_date 之后(盘中未收盘)丢弃。"""
    if not raw:
        return []
    hfq_close = {r[0]: float(r[2]) for r in hfq}
    parsed = [(date.fromisoformat(r[0]), r) for r in raw
              if max_date is None or date.fromisoformat(r[0]) <= max_date]
    if not parsed:
        return []
    ratios = [hfq_close[r[0]] / float(r[2]) if (r[0] in hfq_close and float(r[2]) > 0) else None
              for _, r in parsed]
    # 因子链:从第一行开始,前一行沿用;比值相对变化 > 1e-3 视为除权
    factors: list[float] = []
    for i in range(len(parsed)):
        if i == 0:
            factors.append(1.0)
            continue
        f = factors[-1]
        if ratios[i] and ratios[i - 1] and abs(ratios[i] / ratios[i - 1] - 1) > 1e-3:
            f = f * ratios[i] / ratios[i - 1]
        factors.append(f)
    scale = 1.0
    if ref is not None:
        for i, (d, _) in enumerate(parsed):
            if d == ref.trade_date:
                scale = ref.adj_factor / factors[i]
                break
    vols = [float(r[5]) for _, r in parsed]
    mv_ratio = (ref.total_mv / ref.circ_mv if ref and ref.circ_mv and ref.total_mv else None)
    # 流通股本:优先库内(tushare 精度高);腾讯快照市值与之偏差 >1.5% 视为股本变动,改用快照
    circ_shares = (ref.circ_mv * 1e4 / ref.close if ref and ref.circ_mv and ref.close else None)
    q_shares = None
    if quote and quote.get("circ_mv") and quote.get("close"):
        q_shares = quote["circ_mv"] * 1e4 / quote["close"]
        if circ_shares is None or abs(q_shares / circ_shares - 1) > 0.015:
            circ_shares = q_shares
            mv_ratio = (quote["total_mv"] / quote["circ_mv"]) if quote.get("total_mv") else mv_ratio
    rows = []
    for i, (d, r) in enumerate(parsed):
        if ref is not None and d <= ref.trade_date:
            continue
        close = float(r[2])
        q = quote if (quote and quote.get("date") == d) else None
        if circ_shares:
            circ_mv = close * circ_shares / 1e4
            total_mv = circ_mv * mv_ratio if mv_ratio else None
            turnover = vols[i] * 100.0 / circ_shares * 100.0 if vols[i] else 0.0
        else:
            circ_mv = q["circ_mv"] if q else None
            total_mv = q["total_mv"] if q else None
            turnover = q["turnover_rate"] if q else None
        pb = _pick_pb(q["pb"] if q else None, ref, close)
        if q:
            pe = q["pe"]
        elif ref and ref.close:
            pe = ref.pe * close / ref.close if ref.pe else None
        else:
            pe = None
        prev_close = float(parsed[i - 1][1][2]) if i > 0 else None
        rows.append({
            "code": code, "trade_date": d,
            "open": float(r[1]), "high": float(r[3]), "low": float(r[4]), "close": close,
            "pre_close": (round(prev_close * factors[i - 1] / factors[i], 2)
                          if prev_close else None),
            "vol": vols[i],
            "amount": q["amount"] if q else None,
            "adj_factor": factors[i] * scale,
            "turnover_rate": round(turnover, 4) if turnover is not None else None,
            "volume_ratio": _volume_ratio(vols, i),
            "circ_mv": circ_mv, "total_mv": total_mv,
            "pe": pe, "pb": pb,
        })
    return rows


def rows_from_quotes(day: date, quotes: dict[str, dict], refs: dict[str, RefRow],
                     codes: list[str]) -> list[dict]:
    """收盘后的批量快照 → 当天整市场行。不用逐只拉 K 线(28 个请求搞定全市场):
    - 只取快照日期 == day 的股票(停牌股快照停在旧日期,自然跳过,与 tushare 一致)
    - 因子:昨收(除权参考价)≠ 库内前收盘 → 除权,因子 = 库因子 × 前收盘/昨收;否则沿用
    - 换手/流通市值用库内流通股本(偏差 >1.5% 视为股本变动改用快照);量比用库内前 5 日量"""
    rows = []
    for code in codes:
        q = quotes.get(code)
        if not q or q.get("date") != day or not q.get("close") or q.get("vol") is None:
            continue
        ref = refs.get(code)
        if ref is not None and day <= ref.trade_date:
            continue
        close = q["close"]
        factor = 1.0
        if ref is not None:
            factor = ref.adj_factor
            if q.get("pre_close") and ref.close and abs(q["pre_close"] - ref.close) > 0.0051:
                factor = ref.adj_factor * ref.close / q["pre_close"]
        circ_shares = (ref.circ_mv * 1e4 / ref.close if ref and ref.circ_mv and ref.close else None)
        mv_ratio = (ref.total_mv / ref.circ_mv if ref and ref.circ_mv and ref.total_mv else None)
        if q.get("circ_mv"):
            q_shares = q["circ_mv"] * 1e4 / close
            if circ_shares is None or abs(q_shares / circ_shares - 1) > 0.015:
                circ_shares = q_shares
                mv_ratio = (q["total_mv"] / q["circ_mv"]) if q.get("total_mv") else mv_ratio
        if circ_shares:
            circ_mv = close * circ_shares / 1e4
            total_mv = circ_mv * mv_ratio if mv_ratio else q.get("total_mv")
            turnover = round(q["vol"] * 100.0 / circ_shares * 100.0, 4)
        else:
            circ_mv, total_mv, turnover = q.get("circ_mv"), q.get("total_mv"), q.get("turnover_rate")
        vr = None
        if ref is not None and len(ref.vols5) == 5:
            avg = sum(ref.vols5) / 5
            vr = round(q["vol"] / avg, 2) if avg > 0 else None
        rows.append({
            "code": code, "trade_date": day,
            "open": q["open"], "high": q["high"], "low": q["low"], "close": close,
            "pre_close": q.get("pre_close"), "vol": q["vol"], "amount": q.get("amount"),
            "adj_factor": factor, "turnover_rate": turnover, "volume_ratio": vr,
            "circ_mv": circ_mv, "total_mv": total_mv, "pe": q.get("pe"),
            "pb": _pick_pb(q.get("pb"), ref, close),
        })
    return rows


class BaostockMarketFetcher:
    def __init__(self, lookback_days: int = LOOKBACK_DAYS, log=print,
                 use_baostock: bool = True, tx_klines=tx.klines, tx_quotes=tx.quotes,
                 bs_src: BaostockSource | None = None, query_timeout: float = 60.0):
        self.lookback_days = lookback_days
        self.log = log
        self.use_baostock = use_baostock
        self.tx_klines = tx_klines
        self.tx_quotes = tx_quotes
        self.bs_src = bs_src
        self.query_timeout = query_timeout

    def _start_for(self, ref: RefRow | None, default_start: date) -> date:
        if ref is None:
            return default_start
        return ref.trade_date - timedelta(days=self.lookback_days)

    # ── baostock ──
    def _bs_login(self) -> BaostockSource:
        src = self.bs_src or BaostockSource()
        src._ensure_login(timeout=self.query_timeout)
        return src

    def _bs_one(self, src: BaostockSource, code: str, start: date, end: date,
                ref: RefRow | None) -> list[dict]:
        bs_code = to_bs_code(code)
        k = src._query(src.bs.query_history_k_data_plus(
            bs_code, K_FIELDS, start_date=start.isoformat(), end_date=end.isoformat(),
            frequency="d", adjustflag="3"))
        adj = None
        if needs_adj_query(k, ref):
            adj = src._query(src.bs.query_adjust_factor(bs_code, "1990-01-01", end.isoformat()))
        return rows_from_baostock(code, k, adj, ref)

    def _bs_all(self, codes: list[str], refs: dict, start: date, end: date, out: dict,
                ) -> list[str]:
        """顺序拉;返回没拿到的代码(供腾讯兜底)。连续失败 BREAKER_FAILS 只即熔断。"""
        remaining = list(codes)
        if not remaining or not self.use_baostock:
            return remaining
        try:
            src = self._bs_login()
        except Exception as exc:        # noqa: BLE001
            self.log(f"  baostock login failed: {exc!r} → 全部走腾讯", flush=True)
            return remaining
        t0 = time.time(); streak = 0; n_ok = 0
        for i, code in enumerate(codes):
            ref = refs.get(code)
            rows = None
            for attempt in range(2):
                try:
                    rows = self._bs_one(src, code, self._start_for(ref, start), end, ref)
                    break
                except Exception as exc:    # noqa: BLE001 — 超时/断连:重连一次再试
                    self.log(f"  baostock {code} attempt{attempt}: {exc!r}", flush=True)
                    try:
                        src.close()
                        src = self._bs_login()
                    except Exception:       # noqa: BLE001
                        pass
            if rows is None:
                streak += 1
                if streak >= BREAKER_FAILS:
                    self.log(f"  baostock 连续失败 {streak} 只,熔断;剩余 {len(codes) - i - 1 + streak} "
                             f"只走腾讯", flush=True)
                    src.close()
                    return codes[i + 1 - streak:]
                continue
            streak = 0; n_ok += 1
            remaining.remove(code)
            for r in rows:
                out.setdefault(r["trade_date"], []).append(r)
            if (i + 1) % 500 == 0:
                self.log(f"  baostock {i + 1}/{len(codes)} ({time.time() - t0:.0f}s)", flush=True)
        src.close()
        self.log(f"  baostock done {n_ok}/{len(codes)} in {time.time() - t0:.0f}s", flush=True)
        return remaining

    # ── 腾讯 ──
    def _tx_all(self, codes: list[str], refs: dict, start: date, end: date, out: dict,
                max_date: date | None) -> list[str]:
        if not codes:
            return []
        try:
            qs = self.tx_quotes(codes)
        except Exception as exc:        # noqa: BLE001
            self.log(f"  tencent quotes failed: {exc!r}(成交额/换手/pe/pb 将留空)", flush=True)
            qs = {}

        def one(code):
            ref = refs.get(code)
            beg = self._start_for(ref, start)
            try:
                raw = self.tx_klines(code, beg, end, "")
                # 只有新日期里带除权标记({'cqr':...})的股票才需要 hfq 算因子比值,
                # 其余沿用库内因子 → 请求数减半(腾讯 WAF 对 ~30 req/s 会封 501)
                need_hfq = ref is None or any(
                    len(r) > 6 and isinstance(r[6], dict)
                    for r in raw if date.fromisoformat(r[0]) > ref.trade_date)
                q = qs.get(code)
                if not need_hfq and q and q.get("pre_close") and len(raw) >= 2 \
                        and date.fromisoformat(raw[-1][0]) == q["date"] \
                        and abs(float(raw[-2][2]) - q["pre_close"]) > 0.0051:
                    need_hfq = True          # 快照昨收 ≠ 前收盘:漏标的除权,也查 hfq
                hfq = self.tx_klines(code, beg, end, "hfq") if need_hfq else []
                return code, rows_from_tencent(code, raw, hfq, ref, qs.get(code), max_date)
            except Exception:           # noqa: BLE001
                return code, None
        failed = []
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=4) as ex:
            for n, (code, rows) in enumerate(ex.map(one, codes), 1):
                if rows is None:
                    failed.append(code)
                elif rows:
                    for r in rows:
                        out.setdefault(r["trade_date"], []).append(r)
                if n % 1000 == 0:
                    self.log(f"  tencent {n}/{len(codes)} ({time.time() - t0:.0f}s)", flush=True)
        return failed

    def fetch(self, codes: list[str], refs: dict[str, RefRow], start: date, end: date,
              trading_days: list[date] | None = None) -> dict[date, list[dict]]:
        """返回 {trade_date: rows};只含各股 ref 之后(或无 ref 时 start 起)的新行。
        trading_days: [start, end] 内的交易日历(给快照路径判断"没缺天")。"""
        out: dict[date, list[dict]] = {}
        t0 = time.time()
        codes = sorted(codes)
        # ① 快照路径:最新交易日(收盘后)整市场一次拿齐;只对"库内最后一行就是上一交易日"
        #   的股票用(中间没缺天),其余(缺天/新股)走 ② 逐只 K 线补齐
        need_kline = list(codes)
        if trading_days:
            try:
                qs = self.tx_quotes(codes)
            except Exception as exc:        # noqa: BLE001
                self.log(f"  tencent quotes failed: {exc!r} → 全部走 K 线", flush=True)
                qs = {}
            qdays = [q["date"] for q in qs.values() if q.get("date")]
            qday = max(set(qdays), key=qdays.count) if qdays else None
            if qday and qday in trading_days and (qday < date.today() or _after_close()):
                prev_days = [d for d in trading_days if d < qday]
                prev = prev_days[-1] if prev_days else None
                # 库内最后一行就是上一交易日(或更新)的股票走快照;当天停牌的
                # 快照日期停在旧日期,rows_from_quotes 会自然跳过(与 tushare 一致)。
                # 库内最后一行更早的"缺天"股:零星(≤5%)= 停牌复牌,快照直接给
                # (除权用昨收判),仍停牌的什么都不用拉;大面积 = 漏跑了一天,逐只 K 线补。
                gap = [c for c in codes if refs.get(c) is not None and refs[c].trade_date < prev]
                mass_gap = len(gap) > 0.05 * len(codes)
                quick = [c for c in codes if c not in set(gap)]
                if not mass_gap:
                    quick += [c for c in gap if c in qs and qs[c].get("date") == qday]
                rows = rows_from_quotes(qday, qs, refs, quick)
                if rows:
                    out[qday] = rows
                need_kline = gap if mass_gap else []
                self.log(f"  quotes {qday}: {len(rows)} 行(快照);{len(need_kline)} 只需逐只补 K 线",
                         flush=True)
        main = [c for c in need_kline if not is_bj(c)]
        bj = [c for c in need_kline if is_bj(c)]
        if not need_kline:
            self.log(f"  fetch done in {time.time() - t0:.0f}s, 新日期 {sorted(out)}", flush=True)
            return out
        left = self._bs_all(main, refs, start, end, out)
        # 腾讯盘中已有当天未收盘的 K 线:以 baostock 拿到的最大日期为准截断;
        # baostock 一只都没拿到时退化为"今天之前"(盘后 18:00 后跑才能拿到当天)。
        max_date = max(out) if out else (
            end if (end < date.today() or _after_close()) else end - timedelta(days=1))
        if left:
            self.log(f"  tencent: {len(left)} 沪深" + ("(baostock 兜底)" if self.use_baostock else "")
                     + f" + {len(bj)} 北交", flush=True)
        failed = self._tx_all(left + bj, refs, start, end, out, max_date)
        if failed:
            self.log(f"  tencent failed {len(failed)}: {failed[:10]}", flush=True)
        if codes and len(failed) > MAX_FAIL_RATIO * len(codes):
            raise RuntimeError(f"行情源故障:{len(failed)}/{len(codes)} 只两源都失败 {failed[:10]}")
        self.log(f"  fetch done: {len(main)} 沪深 + {len(bj)} 北交 in {time.time() - t0:.0f}s, "
                 f"失败 {len(failed)}, 新日期 {sorted(out)}", flush=True)
        return out


def _after_close() -> bool:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return (now.hour * 60 + now.minute) >= 7 * 60 + 30   # 15:30 北京 = 07:30 UTC(腾讯收盘即定)


def load_refs(session, lookback_days: int = 60) -> dict[str, RefRow]:
    """每只股票库内最后一行(只扫最近 lookback_days 天,长期停牌的旧股拿不到 ref
    则按新股处理,因子刻度会与其历史断开,可接受)。"""
    from sqlalchemy import select, func
    from app.db.models import DailyQuote
    last = session.scalar(select(func.max(DailyQuote.trade_date)))
    if last is None:
        return {}
    rows = session.execute(
        select(DailyQuote.code, DailyQuote.trade_date, DailyQuote.close,
               DailyQuote.adj_factor, DailyQuote.circ_mv, DailyQuote.total_mv,
               DailyQuote.pe, DailyQuote.pb, DailyQuote.vol)
        .where(DailyQuote.trade_date >= last - timedelta(days=lookback_days))
        .order_by(DailyQuote.trade_date)).all()
    refs: dict[str, RefRow] = {}
    vols: dict[str, list] = {}
    for code, d, close, f, circ, total, pe, pb, vol in rows:
        v = vols.setdefault(code, [])
        v.append(vol or 0.0)
        refs[code] = RefRow(trade_date=d, close=close, adj_factor=f,
                            circ_mv=circ, total_mv=total, pe=pe, pb=pb,
                            vols5=tuple(v[-5:]))
    return refs


def listed_a_shares(src: BaostockSource, day: date) -> list[str]:
    """baostock query_all_stock 里的沪深 A 股股票代码(tushare 格式)。"""
    from app.data.baostock_source import to_ts_code
    src._ensure_login()
    df = src._query(src.bs.query_all_stock(day=day.isoformat()))
    codes = []
    for c in df["code"]:
        ex, sym = c.split(".")
        if (ex == "sh" and sym[:2] in ("60", "68")) or (ex == "sz" and sym[:2] in ("00", "30")):
            codes.append(to_ts_code(c))
    return codes
