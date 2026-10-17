#!/bin/sh
# Runbook: gateway — a loopback-only HTTP gateway inside a container (example).
# A container that is NOT running may be started. A RUNNING container that is silent is a wedge: this script refuses and says so,
# because restarting a running engine is never a heal — a human (or the advisor-gated exact-pid path) decides that.
set -u
CONTAINER=gateway
PORT=8090
HEALTH="curl -fsS --max-time 3 http://127.0.0.1:$PORT/health"
case "${1:-detect}" in
  detect)   $HEALTH 2>/dev/null | grep -q '"ok"' ;;
  heal)     if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then echo "container running but silent: a wedge, not a start — needs a human"; exit 3; fi
            docker start "$CONTAINER" ;;
  verify)   sleep 5; $HEALTH 2>/dev/null | grep -q '"ok"' ;;
  rollback) echo "rollback: a container start that failed leaves nothing to undo; docker logs $CONTAINER"; exit 0 ;;
  *) echo "usage: $0 detect|heal|verify|rollback"; exit 2 ;;
esac
