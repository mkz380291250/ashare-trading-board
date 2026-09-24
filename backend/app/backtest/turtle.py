"""集中持仓盈亏比(海龟式)回测引擎:逐日事件驱动、纯 numpy,独立于 qlib 回测框架。

规则(见 docs/superpowers/specs/2026-09-24-turtle-concentrated-strategy-design.md):
- 收盘后按进场规则选 1 只(每天最多开 1 仓、有空位才选),次日开盘价成交;一字涨停买不到放弃。
- 退出:固定比例(止损 sl、止盈 sl×rr)或 ATR(初始止损 entry−k_stop×ATR,移动止损
  最高收盘−k_trail×ATR);触发顺序 open≤stop 按 open → low≤stop 按 stop → high≥tp 按
  max(open,tp);同日双触按止损;时间止损到期次日开盘;跌停开盘不能卖顺延;数据终止按最后收盘。
- 价格全部在复权空间;涨跌停判定用未复权 open / pre_close。成本 cost/边;每仓资金 = 总资产/slots。
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Params:
    entry: str = "factor"          # factor | breakout
    exit: str = "fixed"            # fixed | atr
    sl: float = 0.06               # fixed: 止损比例
    rr: float = 2.0                # fixed: 止盈 = sl*rr
    k_stop: float = 2.0            # atr: 初始止损 = entry - k_stop*atr
    k_trail: float = 2.0           # atr: 最高收盘回撤 k_trail*atr
    max_hold: int = 0              # 0=不限
    slots: int = 3
    top_n: int = 30                # breakout: 因子前 N
    breakout_n: int = 20           # breakout: 新高窗口 20 | 55(Panel 需有 hi55)
    gate: str = "none"             # none | entry(闸关时不开新仓) | all(闸关时次日开盘清仓且不开仓)
    cost: float = 0.0015
    cash: float = 1_000_000.0
    limit_tol: float = 0.005       # 涨跌停判定容差

    def label(self) -> str:
        ex = (f"sl{self.sl:.2f}_rr{self.rr:g}" if self.exit == "fixed"
              else f"atr{self.k_stop:g}_trail{self.k_trail:g}")
        en = self.entry if self.entry == "factor" else f"{self.entry}{self.breakout_n}"
        g = "" if self.gate == "none" else f"|gate-{self.gate}"
        return f"{en}{g}|{self.exit}:{ex}|hold{self.max_hold or 'inf'}"


@dataclass
class Trade:
    code: str
    entry_i: int
    entry_px: float
    exit_i: int
    exit_px: float
    shares: int
    reason: str                    # stop | tp | trail | time | end

    @property
    def ret(self) -> float:
        return self.exit_px / self.entry_px - 1.0

    @property
    def hold_days(self) -> int:
        return self.exit_i - self.entry_i


@dataclass
class Result:
    nav: np.ndarray
    trades: list
    exposure: np.ndarray
    params: Params | None = None


@dataclass
class Panel:
    """全部 (T, N) float32,nan = 无数据。open/high/low/close 复权;raw_* 未复权。"""
    dates: np.ndarray
    codes: list
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    raw_open: np.ndarray
    raw_pre_close: np.ndarray
    score: np.ndarray
    atr: np.ndarray
    hi20: np.ndarray
    limit: np.ndarray
    hi55: np.ndarray | None = None
    gate: np.ndarray | None = None          # (T,) bool:指数在均线上方=True;None=常开
    _last_valid: np.ndarray = field(default=None, repr=False)

    def last_valid(self) -> np.ndarray:
        """每只票最后一个有收盘价的日索引(全 nan → -1)。"""
        if self._last_valid is None:
            ok = ~np.isnan(self.close)
            T = self.close.shape[0]
            rev = ok[::-1].argmax(axis=0)
            lv = T - 1 - rev
            lv[~ok.any(axis=0)] = -1
            self._last_valid = lv
        return self._last_valid


@dataclass
class _Hold:
    j: int
    entry_i: int
    entry_px: float
    shares: int
    atr: float
    highest: float
    days: int = 0
    pending: str | None = None     # 顺延中的退出原因


def _pick(panel: Panel, t: int, held: set, p: Params) -> int | None:
    s = panel.score[t].copy()
    s[np.isnan(panel.close[t])] = np.nan
    if held:
        s[list(held)] = np.nan
    if np.all(np.isnan(s)):
        return None
    if p.entry == "factor":
        return int(np.nanargmax(s))
    if p.entry == "breakout":
        order = np.argsort(-np.nan_to_num(s, nan=-np.inf))[: p.top_n]
        order = [j for j in order if not np.isnan(s[j])]
        hi = panel.hi20[t] if p.breakout_n == 20 else panel.hi55[t]
        c = panel.close[t]
        for j in order:                      # 已按分数降序
            if not np.isnan(hi[j]) and c[j] > hi[j]:
                return int(j)
        return None
    raise ValueError(f"unknown entry {p.entry}")


def run_turtle(panel: Panel, p: Params) -> Result:
    T, N = panel.close.shape
    lv = panel.last_valid()
    cash = float(p.cash)
    holds: list[_Hold] = []
    trades: list[Trade] = []
    nav = np.empty(T)
    exposure = np.zeros(T)
    last_px = np.full(N, np.nan)
    intent: int | None = None
    prev_nav = cash

    def _exit(h: _Hold, i: int, px: float, reason: str):
        nonlocal cash
        cash += h.shares * px * (1.0 - p.cost)
        trades.append(Trade(panel.codes[h.j], h.entry_i, h.entry_px, i, px, h.shares, reason))

    gate = panel.gate if (p.gate != "none" and panel.gate is not None) else None

    for t in range(T):
        # 0) 趋势闸关(以昨日收盘判定)→ 全部标记次日开盘清仓
        if gate is not None and p.gate == "all" and t > 0 and not gate[t - 1]:
            for h in holds:
                if h.entry_i < t and h.pending is None:
                    h.pending = "gate"
        # 1) 退出
        keep = []
        for h in holds:
            j = h.j
            if h.entry_i >= t:
                keep.append(h)
                continue
            if t > lv[j]:                                   # 数据终止(退市)
                _exit(h, int(lv[j]), float(panel.close[lv[j], j]), "end")
                continue
            c = panel.close[t, j]
            if np.isnan(c):                                 # 停牌:不动
                keep.append(h)
                continue
            o, hi_, lo = panel.open[t, j], panel.high[t, j], panel.low[t, j]
            lim = panel.limit[t, j]
            ro, rpc = panel.raw_open[t, j], panel.raw_pre_close[t, j]
            limit_down = (not np.isnan(ro) and not np.isnan(rpc)
                          and ro <= rpc * (1.0 - lim + p.limit_tol))
            if limit_down:                                  # 跌停开盘不能卖
                h.highest = max(h.highest, c)
                h.days += 1
                if p.max_hold and h.days >= p.max_hold and h.pending is None:
                    h.pending = "time"
                keep.append(h)
                continue
            if h.pending is not None:
                _exit(h, t, float(o), h.pending)
                continue
            if p.exit == "fixed":
                stop = h.entry_px * (1.0 - p.sl)
                tp = h.entry_px * (1.0 + p.sl * p.rr)
                stop_reason = "stop"
            else:
                init = h.entry_px - p.k_stop * h.atr
                trail = h.highest - p.k_trail * h.atr
                stop = max(init, trail)
                tp = np.inf
                stop_reason = "trail" if trail > init else "stop"
            if o <= stop:
                _exit(h, t, float(o), stop_reason)
                continue
            if lo <= stop:
                _exit(h, t, float(stop), stop_reason)
                continue
            if hi_ >= tp:
                _exit(h, t, float(max(o, tp)), "tp")
                continue
            h.highest = max(h.highest, c)
            h.days += 1
            if p.max_hold and h.days >= p.max_hold:
                h.pending = "time"
            keep.append(h)
        holds = keep

        # 2) 执行昨日意向
        if intent is not None:
            j = intent
            intent = None
            o = panel.open[t, j]
            ro, rpc, lim = panel.raw_open[t, j], panel.raw_pre_close[t, j], panel.limit[t, j]
            limit_up = (not np.isnan(ro) and not np.isnan(rpc)
                        and ro >= rpc * (1.0 + lim - p.limit_tol))
            if not np.isnan(o) and not limit_up and len(holds) < p.slots:
                budget = min(prev_nav / p.slots, cash)
                shares = int(budget / (o * (1.0 + p.cost)) // 100) * 100
                if shares > 0:
                    cash -= shares * o * (1.0 + p.cost)
                    holds.append(_Hold(j, t, float(o), shares,
                                       float(panel.atr[t, j]) if not np.isnan(panel.atr[t, j]) else 0.0,
                                       float(o)))

        # 3) 估值
        row = panel.close[t]
        m = ~np.isnan(row)
        last_px[m] = row[m]
        mv = sum(h.shares * last_px[h.j] for h in holds if not np.isnan(last_px[h.j]))
        nav[t] = cash + mv
        exposure[t] = mv / nav[t] if nav[t] else 0.0
        prev_nav = nav[t]

        # 4) 收盘后生成明日意向
        if len(holds) < p.slots and t < T - 1 and (gate is None or gate[t]):
            intent = _pick(panel, t, {h.j for h in holds}, p)

    # 期末强平
    for h in holds:
        i = int(min(lv[h.j], T - 1))
        _exit(h, i, float(panel.close[i, h.j]), "end")
    nav[-1] = cash
    return Result(nav=nav, trades=trades, exposure=exposure, params=p)


def metrics(res: Result, dates, bench_ret=None, lo: int = 0, hi: int | None = None,
            cost: float = 0.0015) -> dict:
    """[lo, hi) 窗口内的指标;nav 按窗口首日归一,trades 按 entry_i 归属窗口。"""
    nav = res.nav[lo:hi]
    if len(nav) < 2 or nav[0] <= 0:
        return {"n_trades": 0}
    nav = nav / nav[0]
    T = len(nav)
    r = np.diff(nav) / nav[:-1]
    ann = float(nav[-1] ** (243.0 / T) - 1.0)
    dd = nav / np.maximum.accumulate(nav) - 1.0
    mdd = float(dd.min())
    sharpe = float(r.mean() / r.std() * np.sqrt(243)) if r.std() > 0 else 0.0
    hi_ = len(res.nav) if hi is None else hi
    trades = [t for t in res.trades if lo <= t.entry_i < hi_]
    rets = np.array([t.ret - 2 * cost for t in trades]) if trades else np.array([])
    pnl = np.array([(t.exit_px - t.entry_px) * t.shares - (t.exit_px + t.entry_px) * t.shares * cost
                    for t in trades]) if trades else np.array([])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    out = {
        "ann": round(ann, 4), "mdd": round(mdd, 4),
        "calmar": round(ann / abs(mdd), 3) if mdd < 0 else 0.0,
        "sharpe": round(sharpe, 3),
        "n_trades": len(trades),
        "win_rate": round(float(len(wins) / len(rets)), 3) if len(rets) else 0.0,
        "avg_win_loss": (round(float(wins.mean() / abs(losses.mean())), 3)
                         if len(wins) and len(losses) and losses.mean() != 0 else 0.0),
        "profit_factor": (round(float(pnl[pnl > 0].sum() / abs(pnl[pnl <= 0].sum())), 3)
                          if len(pnl) and pnl[pnl <= 0].sum() != 0 else 0.0),
        "avg_ret": round(float(rets.mean()), 4) if len(rets) else 0.0,
        "avg_hold": round(float(np.mean([t.hold_days for t in trades])), 1) if trades else 0.0,
        "exposure": round(float(res.exposure[lo:hi].mean()), 3),
        "cum": round(float(nav[-1] - 1.0), 4),
        "reasons": {k: int(sum(1 for t in trades if t.reason == k))
                    for k in ("stop", "tp", "trail", "time", "gate", "end")},
    }
    if bench_ret is not None:
        b = np.asarray(bench_ret)[lo:hi]
        b = np.nan_to_num(b[1:] if len(b) == T else b, nan=0.0)
        bnav = np.cumprod(1.0 + b)
        b_ann = float(bnav[-1] ** (243.0 / T) - 1.0) if len(bnav) else 0.0
        out["bench_ann"] = round(b_ann, 4)
        out["excess_ann"] = round(ann - b_ann, 4)
    return out
