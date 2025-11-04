#!/usr/bin/env bash
set -euo pipefail
TZ=Europe/Paris
export TZ

TARGET="$1"   # "daily-07:00" ou "fri-23:59"
now_hm="$(date +%H:%M)"
dow="$(date +%u)"   # 1=Mon ... 5=Fri ... 7=Sun

case "$TARGET" in
  daily-07:00)
    [[ "$now_hm" == "07:00" ]] && exit 0 || exit 2
    ;;
  fri-23:59)
    [[ "$dow" == "5" && "$now_hm" == "23:59" ]] && exit 0 || exit 2
    ;;
  *)
    exit 3
    ;;
esac
