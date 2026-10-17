"""Shared fixture for the Micro Agent test suite.

Every path is redirected into one temporary MICROAGENT_HOME before microagent.py is imported, and MICROAGENT_DRY=1 is set, so the suite
runs as an ordinary user and never touches /etc/microagent, /var/lib/microagent, a cgroup, a sysctl, or a real process.
Run from the repository root:  python3 -m unittest discover -s tests
"""
import atexit, importlib.util, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOME = Path(tempfile.mkdtemp(prefix="microagent-test-"))
for k in ("MICROAGENT_ETC", "MICROAGENT_STATE"): os.environ.pop(k, None)
os.environ["MICROAGENT_HOME"] = str(HOME)
os.environ["MICROAGENT_DRY"] = "1"
ETC, STATE = HOME / "etc", HOME / "state"
SERVICES = [{"name": n, "port": p, "health": "", "expect": "", "runbook": n} for n, p in
            (("alpha", 59991), ("beta", 59992), ("gamma", 59993), ("delta", 59994))]
CLEAN_RUNBOOK = "#!/bin/sh\n# test runbook: never reboot, never umount, never rm\ncase \"${1:-detect}\" in\n  heal) systemctl start %s.service ;;\n  *) exit 0 ;;\nesac\n"

def write_etc(etc):
    (etc / "runbooks").mkdir(parents=True, exist_ok=True)
    (etc / "services.json").write_text(json.dumps(SERVICES))
    (etc / "config.json").write_text(json.dumps({"tick_s": 300, "boot_grace_s": 0}))
    shutil.copy(REPO / "CONSTITUTION.md", etc / "CONSTITUTION.md")
    for s in SERVICES:
        rb = etc / "runbooks" / f"{s['runbook']}.sh"; rb.write_text(CLEAN_RUNBOOK % s["name"]); rb.chmod(0o755)

write_etc(ETC)
_spec = importlib.util.spec_from_file_location("microagent", REPO / "microagent.py")
ma = importlib.util.module_from_spec(_spec); sys.modules["microagent"] = ma; _spec.loader.exec_module(ma)
atexit.register(shutil.rmtree, HOME, ignore_errors=True)

def reset():
    """Fresh state between tests: empty state dir, no HOLD/HALT/deny/deploy files, clean module memory, verified constitution."""
    shutil.rmtree(STATE, ignore_errors=True); STATE.mkdir(parents=True); (STATE / "disk").mkdir()
    for f in ("HOLD", "HALT_HEAL", "rules_deny.json", "LAST_DEPLOY", "upgrades.json"):
        (ETC / f).unlink(missing_ok=True)
    shutil.copy(REPO / "CONSTITUTION.md", ETC / "CONSTITUTION.md")
    for s in SERVICES:
        (ETC / "runbooks" / f"{s['runbook']}.sh").write_text(CLEAN_RUNBOOK % s["name"])
    for p in (ETC / "runbooks").glob("*.sh"):
        if p.stem not in {s["runbook"] for s in SERVICES}: p.unlink()
    ma._heals.clear(); ma._last_heal.clear(); ma._pending.clear(); ma._fail.clear(); ma._consults.clear(); ma._hm["ts"] = 0
    ma._const.update(ok=None, sha=None, why=""); ma.constitution_check()
    ma.load_known_runbooks()

def journal():
    try: return [json.loads(l) for l in ma.JOURNAL.read_text().splitlines()]
    except FileNotFoundError: return []

def cli(home, *args, env_extra=None):
    """Run the CLI as a separate process against its own MICROAGENT_HOME; returns CompletedProcess."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("MICROAGENT_")}
    env.update({"MICROAGENT_HOME": str(home), **(env_extra or {})})
    return subprocess.run([sys.executable, "-I", str(REPO / "microagent.py"), *args], env=env, capture_output=True, text=True, timeout=120)

def scratch_home():
    h = Path(tempfile.mkdtemp(prefix="microagent-cli-", dir=HOME)); write_etc(h / "etc"); return h
