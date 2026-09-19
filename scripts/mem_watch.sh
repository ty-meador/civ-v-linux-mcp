#!/usr/bin/env bash
# Log Civ5XP's address-space use once a minute until it exits, so a crash can be matched against
# memory growth (32-bit process: ~4 GB ceiling) rather than guessed at. Output: logs/mem_watch.csv
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
PID="$(pgrep -f '/Civ5XP$' | tail -1)"; [ -n "$PID" ] || { echo "Civ5XP not running"; exit 1; }
echo "time,pid,vsz_mb,rss_mb,threads,maps" >> logs/mem_watch.csv
while [ -d "/proc/$PID" ]; do
  echo "$(date +%F_%T),$PID,$(awk '/VmSize/{print int($2/1024)}' /proc/$PID/status),$(awk '/VmRSS/{print int($2/1024)}' /proc/$PID/status),$(ls /proc/$PID/task | wc -l),$(wc -l < /proc/$PID/maps)" >> logs/mem_watch.csv
  command sleep 60
done
echo "$(date +%F_%T),$PID,EXITED,,," >> logs/mem_watch.csv
