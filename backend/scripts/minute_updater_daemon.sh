#!/usr/bin/env bash
# 盘中分钟线采集守护。照 daily_scheduler_daemon.sh 惯例,用 setsid 脱离 harness 启动:
#   setsid bash backend/scripts/minute_updater_daemon.sh >/tmp/minute_updater.out 2>&1 &
# 容器重启后需重新拉起(可由 heartbeat / start_all.sh 兜底)。
set -u

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PY="$BACKEND/.venv/bin/python"
LOG="/tmp/minute_updater.log"
PIDFILE="/tmp/minute_updater.pid"

echo $$ > "$PIDFILE"
echo "[$(date -u +%FT%TZ)] minute_updater daemon started (pid $$), backend=$BACKEND" >> "$LOG"

cd "$BACKEND" && exec "$PY" scripts/minute_updater_daemon.py >> "$LOG" 2>&1
