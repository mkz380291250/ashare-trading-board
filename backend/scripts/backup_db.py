"""把 ashare.db(行情/账户/决策)和 data/tushare_extra.db(tushare 到期前的财报/指数等快照)
做一致性快照(sqlite backup API,不受 WAL/并发写影响)并 gzip 到 backups/<日期>/。
用法: .venv/bin/python scripts/backup_db.py [--keep 4] [--dest backups]
tushare 那部分历史再也下不到了,建议每周跑一次,并把 backups/ 拷一份到容器外。"""
import argparse
import gzip
import shutil
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "ashare.db", ROOT / "data" / "tushare_extra.db"]


def backup_one(src: Path, out_dir: Path) -> Path:
    tmp = out_dir / (src.name + ".tmp")
    con = sqlite3.connect(src)
    dst = sqlite3.connect(tmp)
    con.backup(dst)
    dst.close(); con.close()
    gz = out_dir / (src.name + ".gz")
    with open(tmp, "rb") as f_in, gzip.open(gz, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out, length=16 * 1024 * 1024)
    tmp.unlink()
    return gz


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dest", default=str(ROOT / "backups"))
    p.add_argument("--keep", type=int, default=4)
    a = p.parse_args()
    out_dir = Path(a.dest) / date.today().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in SOURCES:
        if not src.exists():
            print(f"skip {src} (missing)", flush=True)
            continue
        t = time.time()
        gz = backup_one(src, out_dir)
        print(f"{src.name}: {src.stat().st_size / 1e9:.2f} GB -> {gz} "
              f"{gz.stat().st_size / 1e6:.0f} MB in {time.time() - t:.0f}s", flush=True)
    # 只留最近 keep 份
    dirs = sorted(d for d in Path(a.dest).iterdir() if d.is_dir())
    for d in dirs[:-a.keep]:
        shutil.rmtree(d)
        print(f"pruned {d}", flush=True)
    print("BACKUP_DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
