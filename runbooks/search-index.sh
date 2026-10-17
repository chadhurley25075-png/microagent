#!/bin/sh
# Runbook: search-index — a full-text / vector index server started by a user-level supervisor (example).
# Micro Agent runs this as root; the service itself must run as its own user (SERVICE_USER below), never as root.
set -u
SERVICE_USER=svc
PORT=8060
START='cd /srv/search-index && nohup ./bin/search-index --listen 127.0.0.1:8060 >> /srv/search-index/log 2>&1 &'
HEALTH="curl -fsS --max-time 3 http://127.0.0.1:$PORT/health"
case "${1:-detect}" in
  detect)   $HEALTH 2>/dev/null | grep -q '"ok"' ;;
  heal)     # start only if the port is silent; a listening-but-sick process is Micro Agent's decision (exact-pid kill, advisor-gated), not this script's
            ss -ltnH "sport = :$PORT" | grep -q . && { echo "port busy; not starting a second copy"; exit 0; }
            runuser -u "$SERVICE_USER" -- sh -c "$START" ;;
  verify)   sleep 3; $HEALTH 2>/dev/null | grep -q '"ok"' ;;
  rollback) echo "rollback: a failed start leaves nothing to undo; check /srv/search-index/log"; exit 0 ;;
  *) echo "usage: $0 detect|heal|verify|rollback"; exit 2 ;;
esac
