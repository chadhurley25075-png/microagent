#!/bin/sh
# Runbook: primary-db — a relational database behind a systemd unit (example). Phases: detect | heal | verify | rollback.
# Micro Agent calls this as root with ONE argument. Exit 0 = the phase succeeded. Make every phase idempotent and under 60 s.
# Edit UNIT / PORT / HEALTH_CMD for your box. Nothing here deletes data; "heal" only restarts the unit and "rollback" only clears a failed state.
set -u
UNIT=primary-db.service
PORT=5432
HEALTH_CMD='pg_isready -h 127.0.0.1 -p 5432'
case "${1:-detect}" in
  detect)   ss -ltnH "sport = :$PORT" | grep -q . && $HEALTH_CMD >/dev/null 2>&1 ;;
  heal)     systemctl is-active --quiet "$UNIT" && systemctl restart "$UNIT" || systemctl start "$UNIT" ;;
  verify)   sleep 2; $HEALTH_CMD >/dev/null 2>&1 ;;
  rollback) systemctl reset-failed "$UNIT" 2>/dev/null; echo "rollback: nothing to undo for a restart; the unit's own Restart= policy continues" ;;
  *) echo "usage: $0 detect|heal|verify|rollback"; exit 2 ;;
esac
