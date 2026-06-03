from app.data.source import DailyBar


def day_pct(prev_close: float, close: float) -> float:
    return (close - prev_close) / prev_close * 100.0


def has_big_yang(bars: list[DailyBar], window: int = 3, threshold: float = 7.0) -> bool:
    """True if any of the last `window` bars rose > threshold% vs the prior close
    and closed above its open (a real bullish candle)."""
    if len(bars) < 2:
        return False
    n = len(bars)
    for i in range(max(1, n - window), n):
        b, prev = bars[i], bars[i - 1]
        if day_pct(prev.close, b.close) > threshold and b.close > b.open:
            return True
    return False


def not_at_top(bars: list[DailyBar], high_lookback: int = 252, ret_lookback: int = 60,
               high_frac: float = 0.85, max_ret: float = 0.5) -> bool:
    """True if last close <= high_frac * (max high over high_lookback) AND the
    cumulative return over the last ret_lookback bars < max_ret."""
    if not bars:
        return False
    last = bars[-1].close
    high = max(b.high for b in bars[-high_lookback:])
    if last > high_frac * high:
        return False
    ref = bars[-ret_lookback].close if len(bars) > ret_lookback else bars[0].close
    cum_ret = (last - ref) / ref
    return cum_ret < max_ret


def forward_return(entry_close: float, future_close: float | None) -> float | None:
    if future_close is None:
        return None
    return future_close / entry_close - 1.0
