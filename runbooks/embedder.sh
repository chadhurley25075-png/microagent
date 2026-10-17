#!/bin/sh
# Runbook: embedder — an embedding server that needs a few seconds (and a model load) before it answers (example).
# The verify phase waits longer than usual because a cold start is slow; Micro Agent's own +60 s verify covers the rest.
set -u
UNIT=embedder.service
PORT=8081
HEALTH="curl -fsS --max-time 3 http://127.0.0.1:$PORT/health"
case "${1:-detect}" in
  detect)   $HEALTH >/dev/null 2>&1 ;;
  heal)     systemctl restart "$UNIT" ;;
  verify)   i=0; while [ $i -lt 10 ]; do $HEALTH >/dev/null 2>&1 && exit 0; i=$((i+1)); sleep 2; done; exit 1 ;;
  rollback) systemctl reset-failed "$UNIT" 2>/dev/null; echo "rollback: failed state cleared; Micro Agent's cooldown and budget hold the rest"; exit 0 ;;
  *) echo "usage: $0 detect|heal|verify|rollback"; exit 2 ;;
esac
