_EXCHANGES = {"SH", "SZ", "BJ"}


def to_qlib_symbol(code: str) -> str:
    """600519.SH -> SH600519"""
    if "." not in code:
        raise ValueError(f"not a market code: {code}")
    num, ex = code.split(".", 1)
    ex = ex.upper()
    if ex not in _EXCHANGES:
        raise ValueError(f"unknown exchange in {code}")
    return f"{ex}{num}"


def from_qlib_symbol(sym: str) -> str:
    """SH600519 -> 600519.SH"""
    ex = sym[:2].upper()
    if ex not in _EXCHANGES or len(sym) <= 2:
        raise ValueError(f"not a qlib symbol: {sym}")
    return f"{sym[2:]}.{ex}"
