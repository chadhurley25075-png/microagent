# Fresh start — a prompt for an assistant that has never seen Micro Agent

Paste the block below, whole, to an assistant with shell access on the machine where Micro Agent should run. It assumes the assistant has this repository checked out in its working directory and nothing else. Fill in nothing; the assistant asks the human for what it needs.

```
You are installing Micro Agent on this Linux machine for the person you are working with. You have not seen it before. Micro Agent is a root-level caretaker service: one Python file (standard library only) that runs as root from boot, watches a configured list of local services by port and health URL, holds their hot files in RAM, restarts them by runbook under strict budgets, asks a larger model before any kill, writes a wake note for the next assistant session, and journals every act in a hash-chained log. It never deletes, never reboots, and listens on no socket.

Work in this exact order. Do not skip ahead to installing; most of the value is in steps 1–4.

STEP 0 — READ, in this order, completely: README.md, then ARCHITECTURE.md, then SECURITY.md. Do not read the code first; the documents tell you what the code is for. After reading, write down in one paragraph, for the human, what Micro Agent will and will not do on this machine. If you cannot write that paragraph, read again.

STEP 1 — INVENTORY THE BOX, read-only. Run these and retain the output:
  hostname; uname -sm; head -2 /etc/os-release
  ps -p 1 -o comm=                                   # must print systemd for the shipped unit; otherwise read PORTING.md before continuing
  stat -fc %T /sys/fs/cgroup                         # cgroup2fs = cgroup v2; anything else = the floor organ switches itself off
  cat /sys/fs/cgroup/cgroup.controllers              # must contain "memory" for the floor
  free -g; cat /proc/pressure/memory 2>/dev/null     # PSI present?
  df -h                                              # every mount; note anything over 80%
  ss -ltnp                                           # who listens on which port, as which pid and user
  systemctl list-units --type=service --state=running
  python3 --version; which ss journalctl rsync sha256sum ssh
  id -un; ls -la /etc/microagent /var/lib/microagent /opt/microagent 2>&1   # is there already an install?
Record what you found. Do not change anything in this step.

STEP 2 — ASK THE HUMAN. Ask these questions, one block, and wait for the answers. Do not invent answers, do not pick "sensible defaults" for anything in this list:
  a. Which services on this machine matter — the ones that, if they died overnight, would hurt? For each: a short name, the port, and how to tell it is healthy (an HTTP URL on 127.0.0.1 and the text a healthy reply contains, or "the port listening is enough").
  b. Which processes must never be touched by anything automatic? (Name them. They will be left out entirely, or listed with an empty runbook so she only records that they are down.)
  c. Which user do these services run as? (One user. Root will refuse to read files owned by anyone else.)
  d. Where do backups land, and at what time? Is there a second machine or a spare drive that holds a copy? (If there are no backups, say so; that is a fine answer and those organs stay off.)
  e. Which local chat endpoint should be her mind, and which should be her advisor? A URL on 127.0.0.1, a model name, and a timeout, for each. The mind is for notes and one narrow judgement; the advisor must be a larger or more careful model and is the only thing that can say yes to a kill. (If there is no endpoint on this machine: say so. She runs without one; every major act is refused, which is correct.)
  f. Is there an archive that must never be touched, and a spare drive where cold data could be moved? (Paths. If unsure, leave the disk rule off.)
  g. Who should hear about a problem, and how? (A command that takes one argument, or nothing — the wake note is always written.)
  h. Which files are the hot memory of the assistant stack — indexes, context files — that should never wait on the disk? (Paths, owned by the service user, up to 4 GiB total. If none, leave pins off.)
  i. Which processes are model engines (a substring of each command line), and which are interactive assistant sessions (a process name)? The pause reflex must never stop either. Which containers hold guarded data (container names)? Is there test work (benchmarks, batch jobs) that should run in the sandbox slice, and as which user?

STEP 3 — DRAFT THE CONFIGURATION WITH THE HUMAN. From the answers, write:
  - /etc/microagent/services.json   one entry per service from (a), in the order the human cares about them, runbook names matching step 4; services from (b) either omitted or with "runbook": "".
  - /etc/microagent/config.json     copy examples/etc/config.json; set service_user from (c); engine_marks, pause_seat_comms, docker_spine and sandbox_user from (i). Change no other number unless the human asks.
  - /etc/microagent/mind.json and advisors.json from (e), or leave them out.
  - /etc/microagent/pins.json from (h), or leave it out.
  - /etc/microagent/disks.json from (f), or leave it out.
  - /etc/microagent/nightjobs.json and backups.json from (d), or leave them out.
  - /etc/microagent/notify.json from (g), or leave it out.
Every URL and endpoint in every file must be on 127.0.0.1 or a unix socket. Show each file to the human and get a yes on each before the next step.

STEP 4 — ONE RUNBOOK PER SERVICE, WITH THE HUMAN. Read RUNBOOKS.md and the four examples under runbooks/. For each service in services.json with a non-empty runbook, write runbooks/<name>.sh with the four phases (detect, heal, verify, rollback), following AGENTS.md (d) exactly. For each one, tell the human in two sentences what heal does and what it refuses to do, and get a yes. Test every phase by hand as root on the quiet machine and show the exit codes:
  for p in detect heal verify rollback; do sudo sh runbooks/<name>.sh $p; echo "$p -> $?"; done
A heal that restarts a service the human is using is a real event; ask before running that phase.

STEP 5 — DRY RUN, UNPRIVILEGED, BEFORE ANYTHING IS INSTALLED. Point her at a scratch home so she touches nothing:
  export MICROAGENT_HOME=/tmp/ma-dry; rm -rf $MICROAGENT_HOME; mkdir -p $MICROAGENT_HOME/etc/runbooks
  cp <your drafted json files> $MICROAGENT_HOME/etc/; cp runbooks/*.sh $MICROAGENT_HOME/etc/runbooks/
  python3 -I microagent.py tick --dry-run         # one tick; every act is journaled as would_*; read the status it prints
  python3 -I microagent.py status                 # the same, from disk
  python3 -I microagent.py verify                 # chain ok
  python3 -I microagent.py rules show             # runbooks_known must list every runbook you wrote
  python3 -I microagent.py mindgate-test; python3 -I microagent.py sanitize-test; python3 -I microagent.py budget-test
  python3 -I microagent.py nightwatch --test; python3 -I microagent.py scorecard --test
  cp CONSTITUTION.md $MICROAGENT_HOME/etc/; python3 -I microagent.py constitution; python3 -I microagent.py constitution --test
  python3 -I microagent.py neververb-test; python3 -I microagent.py advisor-test; python3 -I microagent.py lesson-test
  unset MICROAGENT_HOME; python3 -m unittest discover -s tests   # the full suite; it makes its own temp dir
  cat $MICROAGENT_HOME/state/journal.jsonl
Every test must print "pass": true, and the suite must end in OK. In the journal, confirm: the "runbooks" line shows missing = [] and refused_never_verb = [] (a refused runbook carries a never-verb: rewrite it); the "would_guard" line names the pids you expect (unprivileged, ss may not show pids for other users — that is normal; root will); nothing is a "heal", only "would_*". If a guarded service reads as down in the dry run and it is actually up, your port or health URL is wrong — fix it now, not after install.

STEP 6 — INSTALL. Only after step 5 is clean and the human says go:
  sudo install -d -m 0755 /etc/microagent /etc/microagent/runbooks
  sudo cp <your drafted json files> /etc/microagent/
  sudo cp runbooks/*.sh /etc/microagent/runbooks/ && sudo chown root:root /etc/microagent/runbooks/*.sh && sudo chmod 0755 /etc/microagent/runbooks/*.sh
  sudo ./deploy.sh                                # /opt/microagent, the unit, /usr/local/bin/microagent, the constitution, the sandbox slice; starts her
  sudo loginctl enable-linger <sandbox user>      # only if (i) named a sandbox user
Configuration goes in before deploy.sh, because the unit starts at its end and the first tick acts on what /etc/microagent holds. deploy.sh refuses (exit 2) when CONSTITUTION.md does not match CONSTITUTION_SHA, never overwrites an existing config; it installs the example runbooks only when the runbooks directory is empty, and it writes LAST_DEPLOY so her first journal line says "deploy", not "crash".

STEP 7 — WATCH ONE FULL TICK AND READ THE JOURNAL BEFORE YOU LEAVE HER RUNNING.
  sleep 65
  microagent journal 40          # expect: boot (reason: deploy by ...), constitution (ok: true), runbooks (known = N, missing = [], refused_never_verb = []), budget_loaded or nothing, guard (pids → -900), sysctl (if min_free was low), floor (if cgroup v2), pin (per file), and no tick_error
  microagent status              # up = the number of services you expect; down = []; guarded = the same names; cg_floor.on true or a stated reason; pinned_mb > 0 if you pinned
  microagent verify              # "ok": true
  microagent wake                # the first wake note; it may say no mind answered — that is fine on a box without a mind
  microagent house               # the one sentence
If anything in the journal surprises you, stop and show it to the human. Do not "fix" it by editing state files.

STEP 8 — HAND OFF: WRITE THE FIRST WAKE NOTE BY HAND. The next assistant session must not open cold. Leave her a note she will carry into the next wake:
  sudo microagent request note '{"text":"Installed <date> by <you>. Guarding: <service names>. Runbooks: <names>. Mind: <name or none>. Advisor: <name or none>. Pins: <n files>. Disk rule: <on/off>. Watch tonight: <the one thing the human said worries them>. Rollback: sudo systemctl disable --now microagent."}'
Then tell the human, in plain words: what is installed, which services she guards, which she only watches, what she will never touch, where the journal is, the three commands to read her (status, journal, wake), and the one-line rollback. Wire /opt/microagent/microagent_wake_hook.sh into the assistant's session start if the human wants sessions to read her note automatically.

NEVER, at any step:
  - Never reboot the machine.
  - Never edit, mask, disable, or restart any unit, timer, or cron entry other than microagent.service.
  - Never delete anything — not a log, not a cache, not a leftover from a previous install. Name it to the human instead.
  - Never expose a port. Nothing in the configuration may name an address other than 127.0.0.1 or a unix socket.
  - Never write a credential into /etc/microagent. A bus token, if ever used, lives in a 0600 file that bus.json names.
  - Never run `microagent floor test`, `sandbox test` or `pause test` without the human present and at least 16 GiB free; they allocate memory on purpose.
  - Never edit CONSTITUTION.md or CONSTITUTION_SHA on the machine. A law change is a repository change and a deploy.
  - Never enable an engine runbook or widen rules. `microagent rules deny` is the only runtime rule change.
  - Never install on a machine where step 1 showed an existing /etc/microagent without first reading its journal and asking the human whether it is theirs.

If at any step you are unsure what the human wants, ask. A question costs a minute; a wrong runbook costs a service.
```
