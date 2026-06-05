#!/usr/bin/env bash
# 本机守护进程:每个交易日(周一~周五)北京时间 17:30(=09:30 UTC)跑一次 daily_full.py。
# 不依赖后端常驻。用 setsid 脱离 harness 启动:
#   setsid bash backend/scripts/daily_scheduler_daemon.sh >/tmp/ashare_sched.out 2>&1 &
# 容器重启后需重新拉起(可由 heartbeat 兜底)。
set -u

BACKEND="$(cd "$(dirname "$0")/.." && pwd)"
PY="$BACKEND/.venv/bin/python"
LOG="/tmp/ashare_daily_sched.log"
PIDFILE="/tmp/ashare_daily_sched.pid"

echo $$ > "$PIDFILE"
echo "[$(date -u +%FT%TZ)] scheduler daemon started (pid $$), backend=$BACKEND" >> "$LOG"

while true; do
  now=$(date -u +%s)
  target=$(date -u -d "today 09:30" +%s)   # 17:30 北京 = 09:30 UTC 同日
  [ "$now" -ge "$target" ] && target=$((target + 86400))
  # 跳过周末:目标落在周六(6)或周日(7)则顺延到下一天
  while :; do
    dow=$(date -u -d "@$target" +%u)
    [ "$dow" -le 5 ] && break
    target=$((target + 86400))
  done
  sleep_s=$((target - now))
  echo "[$(date -u +%FT%TZ)] sleeping ${sleep_s}s until $(date -u -d @$target +%FT%TZ)" >> "$LOG"
  sleep "$sleep_s"

  echo "[$(date -u +%FT%TZ)] RUN daily_full.py" >> "$LOG"
  cd "$BACKEND" && "$PY" scripts/daily_full.py >> "$LOG" 2>&1
  echo "[$(date -u +%FT%TZ)] daily_full.py exit=$?" >> "$LOG"
  sleep 60   # 防止同一分钟内重复触发
done
