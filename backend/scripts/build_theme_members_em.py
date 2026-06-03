"""Build theme -> member stocks from EastMoney concept boards.

Uses the datacenter-web JSON API (no anti-bot, no tushare rate limit) instead of
the blocked push2 endpoint. Board names must match EastMoney exactly. Members are
validated against the quote DB and written to /tmp/theme_members.json, the cache
read by fetch_themes_auto.py / backtest_screener.py.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.screener.themes import EastMoneyThemeSource, datacenter_board_members

DB = str(Path(__file__).resolve().parents[1] / "ashare.db")
OUT = "/tmp/theme_members.json"

# theme -> exact EastMoney concept board names (verified to return members).
THEME_BOARDS = {
    "英伟达链": ["英伟达概念", "CPO概念", "铜缆高速连接"],
    "半导体": ["半导体", "半导体概念", "第三代半导体"],
    "芯片": ["存储芯片", "汽车芯片", "Chiplet概念"],
    "算力": ["数据中心", "东数西算"],
    "电力": ["电力", "特高压", "绿色电力", "虚拟电厂"],
}


def main():
    valid = {
        r[0]
        for r in sqlite3.connect(DB, timeout=60).execute(
            "select distinct code from daily_quotes"
        )
    }
    print(f"DB valid codes: {len(valid)}", flush=True)

    def fetch(board: str) -> list[str]:
        codes = datacenter_board_members(board)
        print(f"  board {board}: {len(codes)} raw", flush=True)
        return codes

    src = EastMoneyThemeSource(THEME_BOARDS, fetch_board=fetch, valid=valid)
    result = {}
    for theme in src.themes():
        codes = src.members(theme)
        result[theme] = codes
        print(f"== {theme}: {len(codes)} stocks in DB ==", flush=True)

    Path(OUT).write_text(json.dumps(result, ensure_ascii=False))
    print(f"WROTE {OUT} sizes={ {k: len(v) for k, v in result.items()} }", flush=True)
    print("MEMBERS_DONE", flush=True)


if __name__ == "__main__":
    main()
