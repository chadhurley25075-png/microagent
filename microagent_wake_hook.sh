#!/bin/bash
# Session-start hook for any assistant session: print the wake note Micro Agent prepared before this terminal opened.
# Wire it into whatever your assistant runs at session start. It prints at most 4000 bytes and never fails the session.
W=${MICROAGENT_STATE:-/var/lib/microagent}/wake.md
[ -r "$W" ] || { echo "=== WAKE — Micro Agent has not written a wake yet (\`microagent wake\`) ==="; exit 0; }
age=$(( $(date +%s) - $(stat -c %Y "$W") ))
if [ "$age" -gt 1800 ]; then echo "=== WAKE is STALE ($((age/60)) min old) — Micro Agent may be down: \`systemctl status microagent\` ==="; fi
head -c 4000 "$W"
