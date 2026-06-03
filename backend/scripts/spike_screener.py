import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


def main():
    import tushare as ts
    pro = ts.pro_api(get_settings().tushare_token)
    # concept membership (Tonghuashun). If gated, note fallback to static lists.
    try:
        idx = pro.ths_index()  # concept/industry index list
        print("ths_index ok", idx.shape, list(idx.columns)[:6])
        sample = idx[idx["type"] == "N"].head(1)["ts_code"].tolist()
        if sample:
            mem = pro.ths_member(ts_code=sample[0])
            print("ths_member ok", sample[0], mem.shape)
    except Exception as e:
        print("CONCEPT GATED ->", repr(e), "(fallback: StaticThemeSource)")
    # earnings: net-profit YoY + revenue YoY
    try:
        fi = pro.fina_indicator(ts_code="600519.SH", period="20251231")
        cols = [c for c in fi.columns if "yoy" in c or "profit" in c]
        print("fina_indicator ok", fi.shape, cols[:8])
    except Exception as e:
        print("EARNINGS GATED ->", repr(e))


if __name__ == "__main__":
    main()
