# Micro Agent

A small caretaker that lives under the login screen and holds your AI's memory alive. It watches, it heals, it refuses, and it leaves a note.

Micro Agent is one Python file, standard library only, that runs as a root service from the moment the kernel is up — before any login, before any assistant session, before any terminal. It holds the handful of services your memory stack depends on (a database, a search index, an embedding server, a gateway), holds their hot files in RAM, restarts them by runbook when they go silent, and writes a short note that the next assistant session reads first thing. It never deletes, never reboots, never kills a process it was not told to guard, and asks a larger model before any act that could hurt. Every act is journaled with the rule that allowed it, in a hash-chained log you can verify.

This document is for someone who will run it on their own machine tonight.

## The two halves

**The hand** is deterministic. It reads ports, pids, health URLs, memory pressure, kernel OOM events and disks; it writes `oom_score_adj`, `vm.min_free_kbytes`, cgroup `memory.low`, and `mlock`; it runs runbooks and sends signals. No model is involved in anything the hand does. If no chat endpoint exists on the machine, the hand runs exactly the same.

**The mind** is a local chat model you point at (a local chat-completions endpoint; a model of roughly 20B parameters or larger gives good notes, smaller ones work with the seed context only). The mind receives a sanitized text frame and returns text. It can reflect, write the wake note, and give a `hold`/`heal` opinion on one narrow class of case. It has no shell, no kill verb, no file writes, and no unfiltered input. The hand decides; the mind explains and proposes.

## What she does for you

| Organ | What it does | Where it lives |
|---|---|---|
| **Guard** | Every guarded pid gets `oom_score_adj -900`; the kernel takes them last. `vm.min_free_kbytes` raised to 1 GiB, previous value saved for rollback. | `guard()`, `sysctl_guard()` |
| **Floor** | cgroup v2 `memory.low` = live RSS x 1.25 on each guarded cgroup and every ancestor, capped at 32 GiB. Soft reservation: the kernel reclaims everything else first. `microagent floor clear` rolls it back. | `cg_floor()` |
| **Pin** | Files named in `pins.json` are `mmap`ed with `MAP_LOCKED` + `MAP_POPULATE` — reads never touch the disk. Cap 4 GiB. | `pin()` |
| **Heal + verify** | Port silent → its runbook. Listening but failing health for 2 ticks → advisor asked → exact pid SIGTERM (SIGKILL after 8 s) → runbook. Verified at +5 s (runbook `verify` phase; `rollback` phase if it fails) and again on the next tick. | `heal()`, `note_heal()`, `verify_heals()` |
| **Budgets** | 3 heals of one service in 60 min → that service is DEAD until a human releases it. More than 6 heals across the set in 10 min → `HALT_HEAL`, a persistent file that survives restarts. Budgets are saved to disk and reloaded at boot. | `budget_ok()`, `load_budget()` |
| **Halt and hold** | `HALT_HEAL`: no heals, everything else continues. `HOLD`: sense and journal only — no guard, no floor, no heals. Both are files under `/etc/microagent`. | `budget_ok()`, `tick()` |
| **Fail-closed** | If `budget.json`, `dead_services.json` or the halt file is unreadable or corrupt, she writes `FAIL_CLOSED` and `HALT_HEAL` and stops healing until `release-heal`. A sick disk never disarms the storm guard. | `fail_closed()` |
| **Boot grace** | For the first 600 s of uptime she journals `would_heal` and does nothing — the machine is still waking and the other services are still starting. | `in_boot_grace()` |
| **Backup scorecard** | Once a day after 07:00, samples random files from each backup copy, hashes them on both sides (ssh for remote hosts), and flags any mismatch or missing file. Read-only. Only files older than the copy's last sync are sampled, so a mismatch is a flaw, never today's growth. | `scorecard_run()` |
| **Night board** | Reads each nightly job's own status file or log and marks it ok / pending / LATE / FAILED against its due time and grace. No scheduler of its own. | `nightwatch()` |
| **Power-return dry run** | After a power-on, probes your network, other machines and engines in rungs and prints who answered and the manual steps for who did not. Probes only. | `power_return()` |
| **The house line** | One plain sentence, refreshed every 60 s, in `house.txt`: "House OK · services 5/5 · backups checked 07:12 · nothing needs you". For the people who live with the machine and do not read JSON. | `house_line()` |
| **Chained journal** | Every act is a JSON line with the rule that allowed it and `prev` = sha256 of the line before. `microagent verify` walks the chain and also checks that no runtime denial was silently widened. | `jlog()`, `verify_chain()` |
| **Tighten-only rules** | At runtime you can deny a verb or a runbook; you cannot add one. Adding is a deploy. A denial that disappears from the deny file without a deploy is reported as tampering. | `rules_deny()`, `rules_tamper()` |
| **Sanitized frame** | Nothing untrusted reaches the mind or `wake.md` verbatim. Free text (log tails, notes, request reasons, advisor reasons) is stripped to `[a-zA-Z0-9 ._/:-]`, cut to 120–300 chars, one line, and wrapped as `[data] ...`. | `clean()`, `data()` |
| **Issue-set thinking** | A full thought (model call) only when the set of things wrong changes, or once an hour. Otherwise a pulse refreshes `wake.md` from rules alone. | `issue_set()`, `mind_due()` |
| **Advisor gate** | A kill, a restart on the mind's say-so, or a release of a hold needs `{"verdict":"approve"}` from an advisor you configure. The question is asked in a thread so the senses never stop. **Nobody answers = NO.** | `consult()`, `_ask_advisor()` |
| **Wake note** | `wake.md`: machine state (rules) + her note (mind) + her last thoughts. Prepared before any terminal opens; a session-start hook prints it. | `write_wake()`, `microagent_wake_hook.sh` |
| **Disk rule** | Never deletes. An archive path is notify-only. When a configured source fills past 90%, one cold (14 d untouched), unused, non-memory folder is copied to a spare drive, every file sha256-verified, the source re-checked unchanged and unused, and only then removed with a symlink left in its place. `microagent disk` is a dry-run plan. | `disk_rule()`, `offload_worker()` |
| **Inbox** | Other sessions may leave notes, set a hold, queue a heal, or set a standing order (checked every tick, up to 7 days). Allowlisted verbs, known service names only, 30 requests per 10 min, every one journaled with its sender. Requests are data, never instructions. | `handle_request()` |
| **Constitution** | `CONSTITUTION.md` holds her eleven laws in plain words. At every start she reads `/etc/microagent/CONSTITUTION.md` and compares its sha256 with `CONSTITUTION_SHA` in the code. A changed or missing file means no heals and no pause reflex until a deploy restores the text; `wake.md` and `status.json` say so. `deploy.sh` refuses to install when the file and the constant disagree. | `constitution_check()`, `deploy.sh` |
| **Never-verbs** | When runbooks load, every runbook file is read as text, comments are dropped, and a runbook whose commands carry a never-verb (`reboot`, `shutdown`, `poweroff`, `kexec`, `umount`, `mkfs`, `wipefs`, `fdisk`, `parted`, `pkill`, `killall`, `rm`, `rmdir`, `shred`, `unlink`, `-delete`, `truncate`, `dd if=`, `docker rm/kill/stop/restart`, `drop database/table`, and a few more) is refused before it can ever run. Engine runbook commands are scanned and flagged the same way. | `refuse_never_verbs()` |
| **Single-use advice** | An advisor's approve is consumed by exactly one act. A second act on the same key asks again. A deny may be re-read for 15 min. | `_take_verdict()`, `consult()` |
| **Known issues** | The second heal of the same service within 7 days appends one `KNOWN ISSUE` line per service per day to `lessons.md` (append-only). `wake.md` carries the last three, so a recurring fault reaches a human as a cause to look at, not as another quiet heal. | `recurrence_check()` |
| **Heal metrics** | Every tick `status.json` carries heals, verified ok, false heals (the next-tick verify failed, or the same service was healed again within an hour), missed heals (a service held down for `dead_ticks` or more with no heal), the false-heal rate, and the refused runbooks. | `heal_metrics()` |
| **Children and containers** | Every descendant of a guarded pid gets the same `oom_score_adj` (a worker forked before the first guard write keeps its parent's old value). Containers named in `config.json` `docker_spine` get it on every pid of their cgroup, every tick, so a restarted container is covered again within one tick. | `guard_kids()`, `docker_guard()` |
| **Sandbox slice** | `microagent-sandbox run <cmd>` runs test work (benchmarks, batch workers, experiments) in `microagent-sandbox.slice`, a user slice of the sandbox user. Every tick she sets its `memory.high` = available + what it holds − guarded floor − 8 GiB (the box keeps 16 GiB), never under 8 GiB, `memory.max` = high + 4 GiB, swap 0, through the user's service manager so a new scope does not reset it. A runaway inside is throttled at high and dies alone at max. | `sandbox()`, `microagent-sandbox` |
| **Pause reflex** | Law 11. When available memory falls under the guarded floor + 4 GiB AND memory PSI full (10 s) passes 10 %, read twice 5 s apart, she sends SIGSTOP to the single largest process that is not guarded or a child of one, not a model engine, not a container, not root-owned, not a system account, not an interactive assistant seat, and not herself (sandbox members first), re-checked by pid and start time. Then she asks an advisor: approve = kill, deny = SIGCONT, silence for 120 s = SIGCONT and an escalation to `wake.md` and the notify command. Its own 10 s loop; disarmed under HOLD, boot grace, or an unverified constitution. | `pause_loop()`, `pause_act()` |
| **Guarded-set pressure** | `status.json` `spine_psi_full10` is the worst `memory.pressure` full avg10 across the guarded services' own cgroups. Box-wide PSI counts time when the only runnable task is stalled, so one throttled sandbox process on an idle box lifts it; the guarded cgroups' own pressure is the gauge of their health, and a throttled sandbox alone does not count as memory stress. | `_spine_cg_psi()`, `stressed()` |

## What she never does

- Never deletes a file, with one exception: a folder the disk rule has already copied and hashed, file by file, to a spare drive.
- Never reboots, never unmounts, never changes another unit's definition.
- Never kills by name. Only the exact pid that owns a guarded port, re-checked at the moment of the signal; never a container proxy; never a process owned by a user other than root or the configured service user.
- Never restarts a running engine. A running container that is silent is a wedge; the example `gateway` runbook refuses and says so.
- Never runs a runbook that was not present under `/etc/microagent/runbooks` at boot, or that is not root-owned, or that is group/world-writable.
- Never acts on the mind alone. Rules first; the mind only sees the residue; the advisor must approve.
- Never heals under memory stress (PSI full60 ≥ 10 or under 4 GiB available), during boot grace, under a hold, past a budget, or while fail-closed.
- Never feeds untrusted text to a model verbatim.
- Never runs a runbook whose commands carry a never-verb; it is refused when runbooks load.
- Never heals while the constitution is unverified.
- Never spends one approve on two acts.
- Never kills on silence. The pause reflex sends SIGSTOP and SIGCONT; a kill needs an advisor's approve.
- Never widens its own rules at runtime.
- Never exposes a port. She listens on nothing. The optional message bus is a client connection you configure; it is off by default.

## Who it is for

Anyone running a local memory or retrieval stack for an AI assistant on a Linux box they own: a database, an index, an embedding server, a gateway, a model engine. Especially anyone who has lost that stack overnight to an OOM kill, a crash loop, a full disk, or a power cut, and found out the next morning from a cold assistant session. Micro Agent is the thing that was awake.

## Requirements

- Linux with root. Tested on cgroup v2 with the memory controller enabled (`/sys/fs/cgroup/cgroup.controllers` contains `memory`). Without cgroup v2 the floor organ switches itself off and everything else works.
- Python 3.9 or newer. Standard library only. No packages.
- systemd as the init system (the unit, `systemctl`, `systemd-run`). PORTING.md covers other init systems.
- `ss` (iproute2), `sha256sum` (coreutils; `deploy.sh` uses it), `journalctl` (for OOM counts; without it the count reads 0), `rsync` (disk rule only), `ssh` (backup scorecard on remote hosts only), the `docker` CLI (container guard only), `runuser` (util-linux; the sandbox sizing and the service-user runbooks).
- For the sandbox slice: a user service manager for the sandbox user that runs without a login (`sudo loginctl enable-linger <user>`). Without it the sandbox organ reports "slice not started" and everything else works.
- For the mind: a local chat-completions endpoint on loopback. Roughly 20B parameters or larger gives good notes; anything that answers the wire format works. The hand needs none.
- For the advisor: a second, larger endpoint, or a command that prints JSON. Optional; without one, every major act is refused, which is the safe default.

## Install

Configure first, then deploy: the unit starts at the end of `deploy.sh`, and its first tick acts on whatever `/etc/microagent` holds at that moment.

```sh
git clone <this repo> microagent && cd microagent
python3 -m unittest discover -s tests                                   # the test suite, as an ordinary user; touches nothing outside a temp dir
MICROAGENT_HOME=/tmp/ma-dry python3 -I microagent.py tick --dry-run     # unprivileged dry run; touches nothing outside /tmp/ma-dry
sudo install -d -m 0755 /etc/microagent /etc/microagent/runbooks
sudo cp examples/etc/config.json examples/etc/services.json /etc/microagent/   # then edit both: your tunables, services, ports, health URLs, runbook names
sudo cp runbooks/*.sh /etc/microagent/runbooks/                         # one runbook per service; edit them (RUNBOOKS.md), keep them root-owned 0755
sudo ./deploy.sh                                                        # /opt/microagent, the unit, the CLI, the constitution, the sandbox slice; starts her
microagent status                                                       # the first tick
microagent verify                                                       # the chain is intact
microagent constitution                                                 # the law text verified (exit 0)
```

`deploy.sh` checks the constitution hash before it installs anything (exit 2 on a mismatch), installs example runbooks only when `/etc/microagent/runbooks` is empty, and `config.json`/`services.json` only when absent. It never overwrites your configuration. It writes `/etc/microagent/LAST_DEPLOY` so she can tell a deploy from a crash. After a change to `config.json`, `services.json` or a runbook, `sudo systemctl restart microagent`; `upgrades.json` is read every tick and needs no restart.

For the sandbox slice, once per sandbox user: `sudo loginctl enable-linger <user>`, then as that user `microagent-sandbox status`.

To print the wake note at the start of every assistant session, run `/opt/microagent/microagent_wake_hook.sh` from whatever your assistant executes at session start.

## Configuration reference

All files under `/etc/microagent`. Every file is optional; a missing file means that organ has nothing to do.

| File | Format | Meaning |
|---|---|---|
| `config.json` | object | Tunables, read at start. Defaults: `tick_s` 300 · `reflect_every` 6 ticks · `min_free_kb` 1048576 (0 leaves the sysctl alone) · `oom_adj` -900 · `pin_cap_bytes` 4 GiB · `heal_cooldown_s` 600 · `dead_ticks` 2 · `svc_budget` [3, 3600] · `set_budget` [6, 600] · `stress_psi_full60` 10.0 · `stress_avail_gb` 4.0 · `self_anon_max_kb` 1 GiB · `boot_grace_s` 600 (seconds of machine uptime) · `service_user` "" · `floor_max_bytes` 32 GiB · `floor_margin` 1.25 · `mind_full_floor_s` 3600 · `gpu_temp_command` "" (a shell command that prints degrees C) · `recur_n` 2 and `recur_days` 7 (known-issue lessons) · `docker_spine` [] (`[{"container", "label"}]`) · `sandbox_user` "" (defaults to `service_user`) · `sandbox_slice` "microagent-sandbox.slice" · `pause_never_comm` [] (process names added to the never-pause list) · `pause_seat_comms` [] (process names of interactive assistant seats) · `pause_batch_flag` " -p " (a seat process whose command line carries it is a batch worker, not a seat) · `engine_marks` [] (command-line substrings of model engines; such a process is never paused). |
| `services.json` | array | `[{"name", "port", "health" (URL or ""), "expect" (substring the 200 body must contain, or ""), "runbook" (name of `runbooks/<name>.sh` or ""), "user" (optional)}]`. Order is the order she checks. A service with no health URL is healthy when its port listens. |
| `pins.json` | array of paths | Files to mlock, in priority order, up to `pin_cap_bytes`. Must be regular files owned by root or the service user. |
| `mind.json` | object | `{"context_full": path, "context_seed": path, "endpoints": [{"name", "url", "model", "timeout", "seed_only"?, "headers"?, "extra"?}]}`. Endpoints are tried in order; the first non-empty answer wins. Context files are placed first in the system prompt so an engine's prefix cache hits. |
| `advisors.json` | array | `[{"name", "url", "model", "timeout", "readiness_file"?, "enabled"?}]` or `{"name", "type": "command", "command", "timeout"}`. Tried in order. A `readiness_file` is `{"ts": epoch, "serving": bool, "hold": bool, "jobs": n}` written by the advisor's own monitor; stale (>150 s), not serving, held or busy = skipped. |
| `identity.txt` | text | The mind's system prompt. Default inside the code. Retain the sentence starting "When you reflect" — the wake-note and judge prompts split on it. |
| `disks.json` | object | `{"watch": {name: path}, "archive": {"path"}, "offload": {"from", "to", "to_mount", "to_uuid", "trigger_pct" 90, "to_max_pct" 85, "cold_days" 14, "never_words", "never_tokens"}}`. |
| `nightjobs.json` | array | `[{"name", "due": "HH:MM", "grace_min", "probe": {...}}]`. Probe types: `json_status` (`path` → `{"day","finished"}`), `log_line` (`path`, `must`, `fail`), `file_today` (`path`), `files_today` (`paths`). |
| `backups.json` | array | `[{"name", "host" (ssh host or null), "job" (a nightjobs name, for the sync time), "map": [[src, dst]...], "exclude": [...], "removable": bool}]`. |
| `power_return.json` | object | `{"silent_ip", "rungs": [{"title", "probes": [{"name", "tcp": "host:port"} or {"name", "http", "expect"}], "manual": {name: text}}], "services_manual"}`. |
| `endpoints.json` | object | `{display name: {"http": url, "expect"}}` — the larger things the house line counts as "engines". |
| `bus.json` | object | `{"enabled": false, "module", "url", "token_file", "subject"}`. Off by default. See ARCHITECTURE.md. |
| `notify.json` | object | `{"command": ""}`. A command that receives one argument (the message). Empty = wake.md and notes only. |
| `upgrades.json` | object | Read every tick. Per-organ switches, all default true: `floor thermal scorecard nightwatch power_return house rules disk dialogue sandbox pause docker_guard guard_kids`. Off = that organ senses nothing and writes nothing. Tunables: `pause_avail_margin_gib` 4.0 · `pause_psi_full10` 10.0 · `pause_deadline_s` 120 · `pause_cooldown_s` 900 · `pause_min_rss_mib` 256 · `sandbox_reserve_gib` 8.0 · `sandbox_min_gib` 8.0 · `sandbox_box_min_gib` 16.0 · `sandbox_notch_gib` 4.0. |
| `CONSTITUTION.md` | text, root 0644 | The law text, installed by `deploy.sh`. Its sha256 must equal `CONSTITUTION_SHA` in `microagent.py`. To change a law: edit `CONSTITUTION.md` in the repo, put `sha256sum CONSTITUTION.md` into `CONSTITUTION_SHA`, run `deploy.sh`. |
| `engine_runbooks.json` | object | Shadow runbooks for large engines. Ships empty. Only `--dry-run` exists. See RUNBOOKS.md. |
| `rules_deny.json` | object | `{"verbs": [...], "runbooks": [...], "ts", "by"}`. Written by `microagent rules deny`. Only ever grows at runtime. |
| `runbooks/<name>.sh` | shell | One per service. Must be root-owned, mode without group/world write. See RUNBOOKS.md. |
| `HOLD` | any content | Present = sense and journal only. |
| `HALT_HEAL` | JSON | Present = no heals. Written by the set budget, by fail-closed, or by `microagent halt-heal`. |
| `LAST_DEPLOY` | JSON | `{"ts", "by", "reason"}` written by `deploy.sh`. A boot within 300 s of it is reported as a deploy. |

State under `/var/lib/microagent` (root-owned, world-readable where noted):

| File | Format | Meaning |
|---|---|---|
| `status.json` | object, 0644 | The last tick, in full. `microagent status` prints it. |
| `journal.jsonl` | JSON lines | The chained journal. Each line: `{"ts", "kind", ..., "prev"}`. |
| `thoughts.jsonl` | JSON lines | `{"ts", "brain", "thought"}` — her reflections and the advisor's replies. |
| `wake.md` | text, 0644, ≤4000 bytes | The wake note. |
| `budget.json` | object | `{"heals": [[ts, name]...], "last_heal": {name: ts}}`. Corrupt = fail-closed. |
| `dead_services.json` | object | `{name: "when"}`. Corrupt = fail-closed. |
| `FAIL_CLOSED` | JSON | `{"ts", "why"}`. Present = no heals. |
| `sysctl_prev.json` | object | The `vm.min_free_kbytes` value before she raised it. |
| `cg_floor.json` | object | `{cgroup path: bytes}` — every `memory.low` she set. `floor clear` releases them. |
| `notes.jsonl` | JSON lines | Messages left for her (`{"ts", "from", "text"}`). She reads the last 24 h in her frame. |
| `requests.jsonl`, `queue.json`, `standing.json` | JSON | Inbox results, queued acts, standing orders. |
| `restore_scorecard.json`, `nightwatch.json`, `power_return.json` | object | The last run of each organ. |
| `house.txt`, `house.json` | text / object, 0644 | The house line. |
| `advisor_dialogue.json` | object | When she last handed a thought to the first advisor (at most every 3 h). |
| `talks.jsonl` | JSON lines | Transcripts from `microagent talk`. |
| `disk/` | directory | `waiting.json` (things waiting on a human), `blocked.json`, `notified.json`, `<folder>.manifest.json`, `<folder>.inflight`. |
| `lessons.md` | text, append-only | `- KNOWN ISSUE <day> <service>: healed Nx in 7 d ...` lines. `microagent lessons` prints it. |
| `sandbox.json` | object | The sandbox slice's last sizing: usage, high, max, floor, kernel events, slice pressure, throttled. |
| `pause.json` | object | The pause reflex's last 50 acts (`paused`, `killed`, `resumed_deny`, `resumed_silence`, `escalated`). |

`MICROAGENT_HOME=/some/dir` relocates both trees to `/some/dir/etc` and `/some/dir/state`; `MICROAGENT_ETC` and `MICROAGENT_STATE` set them individually. When she is not root, or `--dry-run` is given, or `MICROAGENT_DRY=1`, every act becomes a `would_*` journal line and nothing outside the state directory is written.

## The verbs

Inbox verbs, accepted from `microagent request <verb> '<json args>' [reason]` (and from the bus when enabled). All eleven, with exact semantics:

| Verb | Args | What happens | When |
|---|---|---|---|
| `status` | — | Returns `status.json`. | Immediately. |
| `thoughts` | `{"n": ≤20}` | Returns the last n thoughts. | Immediately. |
| `journal` | `{"n": ≤50}` | Returns the last n journal lines. | Immediately. |
| `note` | `{"text"}` | Appends to `notes.jsonl`. She reads it, `[data]`-wrapped, in her next frame; the next wake carries it. | Immediately. |
| `hold` | — | Writes `HOLD` with the sender and reason. | Immediately. |
| `release` | — | Queued. Needs the advisor's approve. On approve, `HOLD` is removed. | Next tick, after the advisor. |
| `heal` | `{"service"}` | Queued. The service must be in `services.json`. Healthy → nothing. Port silent → its runbook under every budget. Listening but sick → advisor asked, then exact-pid kill + runbook. | Next tick, after the advisor where needed. |
| `standing` | `{"service", "on": "down"\|"unhealthy", "do": "note"\|"heal", "days": ≤7}` or `{"metric", "above"/"below", "do": "note", "days"}` | Sets an order checked every tick, fired at most every 30 min, expiring after `days`. Metrics: `mem_avail_gb psi_full60 oom_kills_1h disk_root`. Max 20 orders. | Immediately; fires on later ticks. |
| `standing_list` | — | Returns live orders. | Immediately. |
| `cancel` | `{"id"}` | Removes one order. | Immediately. |
| `result` | `{"id"}` | Returns the recorded result of a queued request, and whether it is still queued. | Immediately. |

Every request is rate-limited (30 per 10 min), size-capped (8 KiB), journaled with its sender, and answered with an id. A queued act that the advisor never answers in 30 min is recorded as "not done".

## Exit and return codes

- `microagent verify`: exit 0 when the chain has no breaks and no denial vanished; exit 1 otherwise.
- `microagent constitution`: exit 0 when the deployed text hashes to `CONSTITUTION_SHA`; exit 1 otherwise.
- `deploy.sh`: exit 2 when `CONSTITUTION.md` does not hash to `CONSTITUTION_SHA` (nothing is installed); exit 1 when not root.
- `microagent rules deny`: exit 0 on success; exit 2 on refusal or bad arguments. `rules allow|add|widen` always exit 2.
- `microagent engine-runbook <name>` without `--dry-run`: refuses and exits non-zero.
- `serve`, `tick`, `reflect`, `wake write`, `talk`, `disk`, `floor`, `scorecard --now`, `rules deny`: exit with a message when not root and no `MICROAGENT_HOME` is set.
- `budget-test`, `sanitize-test`, `lesson-test`: refuse to run against the live state directory.
- `sandbox`, `pause`: exit with a message when not root.
- An unknown command prints the usage and exits 2.
- `serve` exits 3 when her own anonymous memory passes the cap; the unit's `Restart=always` brings a fresh process back in 10 s and the next boot line says "self-restart".
- Runbook phases: exit 0 = succeeded. The example `gateway` runbook exits 3 for "running but silent; needs a human".

## Security model

- Root executes nothing from a user's home. The program and interpreter are root-owned under `/opt/microagent`; `python3 -I` ignores `PYTHON*` variables and the user site directory.
- Root reads a few user-owned files (pins, context, readiness, night logs) through `owned_file()`: `O_NOFOLLOW`, then `fstat` must show a regular file owned by root or the configured service user. A planted symlink cannot make root read `/etc/shadow` into a model prompt.
- Runbooks run only if they were present at boot (default deny), are root-owned, and are not group/world-writable. They run as root with one argument; anything run as the service user goes through `runuser`.
- The mind and the advisor receive text and return text. Their output is parsed for one JSON object with a `verdict`; anything else is `hold` / `deny`.
- The inbox accepts allowlisted verbs with known service names only; free text is sanitized before it reaches any frame.
- She listens on no socket. The bus, when enabled, is an outbound client connection to a server you run.
- The pause reflex sends SIGSTOP and SIGCONT only, to a process that passes every exclusion and whose pid and start time are re-read at the signal. A kill from the reflex needs an advisor's approve, which is single-use.
- A runbook carrying a never-verb is refused when runbooks load; the constitution's hash gates every heal.

See SECURITY.md for the threat model and the never-list in full.

## How to verify what it does

```sh
microagent verify                       # journal chain intact, no denial vanished since the last deploy
microagent journal 50                   # every act, with the rule that allowed it
microagent status                       # the last tick in full
microagent wake                         # the note the next session reads
microagent house                        # the one sentence
microagent rules show                   # active verbs, denied verbs/runbooks, known runbooks, organ switches
sudo microagent tick --dry-run          # one tick with every act journaled as would_* and nothing written outside state
sudo microagent disk                    # the disk rule's plan; never moves anything
sudo microagent power-return            # who answers, who needs a button; probes only
sudo microagent engine-runbook --dry-run
MICROAGENT_HOME=/tmp/x microagent mindgate-test     # 2 h of quiet at 5-min ticks → ≤2 full thoughts; a HOLD → full within one tick
MICROAGENT_HOME=/tmp/x microagent sanitize-test     # an injected instruction never reaches the frame or wake.md verbatim
MICROAGENT_HOME=/tmp/x microagent budget-test       # a corrupt budget file → FAIL_CLOSED + HALT_HEAL, no heals
MICROAGENT_HOME=/tmp/x microagent nightwatch --test # a stale status file past its deadline → LATE
MICROAGENT_HOME=/tmp/x microagent scorecard --test  # one corrupted byte in a scratch copy → flagged
sudo microagent floor test              # a synthetic 8 GiB hog in a 4 GiB-capped cgroup dies alone; every guarded pid holds on to its memory (needs ≥16 GiB free)
microagent constitution                 # the deployed law text and whether it verifies
MICROAGENT_HOME=/tmp/x microagent constitution --test   # the shipped text verifies; one changed word and a missing file both fail
microagent neververb-test               # a clean runbook passes; one that reboots, one that unmounts, one that deletes are refused
microagent advisor-test                 # an approve is handed out once, then reads as spent; a deny re-reads; an unanswered ask reads as asking
MICROAGENT_HOME=/tmp/x microagent lesson-test       # two heals of one service → exactly one KNOWN ISSUE line
microagent metrics                      # heal metrics, known issues, constitution
sudo microagent pause candidates        # who the reflex would pick right now, and why every other large process is excluded
sudo microagent pause status            # armed, the two conditions, recent acts
sudo microagent sandbox status          # the slice's sizing and usage
sudo microagent docker-guard            # container and descendant guard, one pass
sudo microagent sandbox test            # a synthetic hog inside the slice under a temporary 4 GiB cap is throttled; guarded pids untouched (needs ≥16 GiB free)
sudo microagent pause test              # a synthetic sandbox hog: silence → resumed, deny → resumed, approve → killed, with a stub advisor
```

## Tests

`tests/` is a standard-library `unittest` suite. It runs as an ordinary user, needs no network and no root, and redirects every path into one temporary directory (`MICROAGENT_HOME`, with `MICROAGENT_DRY=1`) before it imports `microagent.py`. No signal reaches any process except the suite's own child, and only SIGSTOP and SIGCONT.

```sh
python3 -m unittest discover -s tests          # from the repository root
```

It covers the hash-chained journal and `verify` on a tampered or removed line; the sanitizer (control characters, markup, injection text, length caps, `[data]`); the heal budgets (3 per service per hour → DEAD, more than 6 across the set in 10 min → HALT_HEAL, persisted and reloaded); fail-closed on corrupt budget, dead-services, halt and fail-closed files; tighten-only rules and the tamper report; never-verb refusal at load; the constitution hash gate on heals and on `deploy.sh`; boot grace (`would_heal` only, from the module and from `config.json`); single-use advisor verdicts; and the pause reflex (SIGSTOP and SIGCONT only on silence or deny, a kill only after an approve, no signal to a changed pid, no signal in a dry run, the exclusion rules).

Rollbacks, one line each: `sudo microagent floor clear` (memory.low floors) · `sudo sysctl vm.min_free_kbytes=$(jq .\"vm.min_free_kbytes\" /var/lib/microagent/sysctl_prev.json)` · `sudo microagent release-heal` (halt, dead marks, fail-closed) · `sudo microagent release` (hold) · `sudo systemctl disable --now microagent` (all of it; nothing she set persists past the next boot except the symlinks the disk rule left, which still resolve) · the sandbox slice's runtime sizing: `systemctl --user revert microagent-sandbox.slice` as the sandbox user (the unit file's standing values return).

## Documents

- ARCHITECTURE.md — the tick loop in order, data structures, the chain, the budgets, the advisor ladder, the sanitizer, failure modes.
- AGENTS.md — ready-to-paste prompts: the mind frame, the advisor, an operator agent, a runbook author, a session wake.
- RUNBOOKS.md — the runbook format and the four examples explained.
- SECURITY.md — threat model, the never-list, how to report an issue.
- FRESH-START.md — a complete prompt for an assistant installing Micro Agent on a new box.
- PORTING.md — other init systems, no cgroups, BSD and macOS, containers, other architectures, another bus, another model wire format, several machines.
- SUB-OS.md — what a caretaker below the OS can and cannot do, mechanism by mechanism.
- CONSTITUTION.md — the eleven laws she loads and hash-verifies at every start.
- tests/ — the standard-library test suite (`python3 -m unittest discover -s tests`).

Copyright 2026 Chad Hurley. Apache License 2.0 — see LICENSE and NOTICE.
