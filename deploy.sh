#!/bin/bash
# Deploy Micro Agent: this checkout → /opt/microagent (root-owned), the unit → /etc/systemd/system, the CLI → /usr/local/bin/microagent,
# the written law → /etc/microagent/CONSTITUTION.md, the sandbox slice → /etc/systemd/user + /usr/local/bin/microagent-sandbox.
# Run from the repo root with sudo. Config under /etc/microagent is NEVER overwritten by this script; runbooks are installed only when
# /etc/microagent/runbooks is empty (first install) — after that you own them.
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
python3 -I -m py_compile "$SRC/microagent.py"
# The constitution must hash to CONSTITUTION_SHA in microagent.py, or nothing is installed (she would refuse every heal at start).
want=$(python3 -I -c 'import re,sys; print(re.search(r"CONSTITUTION_SHA = \"([0-9a-f]{64})\"", open(sys.argv[1]).read()).group(1))' "$SRC/microagent.py")
have=$(sha256sum "$SRC/CONSTITUTION.md" | cut -c1-64)
[ "$want" = "$have" ] || { echo "REFUSED: CONSTITUTION.md sha256 $have != CONSTITUTION_SHA $want in microagent.py — put the new hash in the code or restore the text"; exit 2; }
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
install -d -o root -g root -m 0755 /opt/microagent /etc/microagent /etc/microagent/runbooks /var/lib/microagent /etc/systemd/user
install -o root -g root -m 0755 "$SRC/microagent.py" /opt/microagent/microagent.py
install -o root -g root -m 0644 "$SRC/README.md" /opt/microagent/README.md
install -o root -g root -m 0644 "$SRC/CONSTITUTION.md" /opt/microagent/CONSTITUTION.md
install -o root -g root -m 0644 "$SRC/CONSTITUTION.md" /etc/microagent/CONSTITUTION.md
install -o root -g root -m 0644 "$SRC/microagent.service" /etc/systemd/system/microagent.service
install -o root -g root -m 0755 "$SRC/microagent_wake_hook.sh" /opt/microagent/microagent_wake_hook.sh
install -o root -g root -m 0755 "$SRC/microagent-sandbox" /usr/local/bin/microagent-sandbox
install -o root -g root -m 0644 "$SRC/microagent-sandbox.slice" /etc/systemd/user/microagent-sandbox.slice
ln -sf /opt/microagent/microagent.py /usr/local/bin/microagent
if [ -z "$(ls -A /etc/microagent/runbooks)" ]; then
  for rb in "$SRC"/runbooks/*.sh; do install -o root -g root -m 0755 "$rb" /etc/microagent/runbooks/; done
  echo "installed example runbooks into /etc/microagent/runbooks (edit them; they are yours now)"
fi
for f in config.json services.json; do
  [ -e "/etc/microagent/$f" ] || install -o root -g root -m 0644 "$SRC/examples/etc/$f" "/etc/microagent/$f"
done
# Leave her a note so she knows this restart is a deploy, not a crash (DEPLOY_BY / DEPLOY_REASON may be set in the environment).
python3 -I - <<'PY' > /etc/microagent/LAST_DEPLOY
import json, os, time
print(json.dumps({"ts": time.time(), "by": os.environ.get("DEPLOY_BY") or (os.environ.get("SUDO_USER") or os.environ.get("USER", "?")) + "@" + os.uname().nodename,
                  "reason": os.environ.get("DEPLOY_REASON", "deploy.sh")}))
PY
chmod 0644 /etc/microagent/LAST_DEPLOY
systemctl daemon-reload
systemctl enable --now microagent.service
systemctl restart microagent.service
sleep 5
systemctl is-active microagent.service
microagent verify >/dev/null && echo "deployed; journal chain ok at +5 s"
microagent constitution >/dev/null && echo "constitution verified ($have)"
