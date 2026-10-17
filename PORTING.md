# Porting

Micro Agent is one file of standard-library Python. Everything platform-specific is a short function with a name you can grep for. This document says, for each kind of move, which functions change and what they must still promise.

The promises that must survive any port: the hand never acts on a model's words alone; a runbook runs only if known at boot; budgets persist across restarts; a corrupt budget means no heals; every act is journaled with its rule and chained; untrusted text is sanitized before a model sees it; no advisor means no major act.

## (a) Other init systems

What the shipped `microagent.service` gives her, and the replacement under each init:

| systemd directive | What it does for her | OpenRC | runit | s6 | BSD rc.d | macOS launchd |
|---|---|---|---|---|---|---|
| `Restart=always`, `RestartSec=10` | brings her back after `self_restart` (exit 3) and after any crash | `supervisor=supervise-daemon` + `respawn_delay=10` in the init script | the `run` script is restarted automatically; add `sleep 10` at its top | s6-supervise restarts by default; a `finish` script can delay | `rc.d` does not supervise; use `daemon -r -R 10` (FreeBSD) or a cron `@reboot` + a watchdog script | `KeepAlive` → `<true/>` with `ThrottleInterval` 10 |
| `StateDirectory=` / `ConfigurationDirectory=` | creates `/var/lib/microagent` and `/etc/microagent` root-owned at start | `checkpath -d -o root:root -m 0755` in `start_pre` | `mkdir -p` in `run` | `mkdir -p` in `run` | `mkdir -p` in the rc script's `start_precmd` | `mkdir -p` in a wrapper script; or let `microagent.py` do it (it already does, line `for _d in (ETC, STATE, ...)`) |
| `OOMScoreAdjust=-1000` | the kernel takes her last | `echo -1000 > /proc/$$/oom_score_adj` before `exec` in the script | same, in `run` | same | no OOM score on BSD; see (d) | no equivalent; see (d) |
| `LimitMEMLOCK=infinity` | lets `pin()` mlock up to `pin_cap_bytes` | `rc_ulimit="-l unlimited"` | `ulimit -l unlimited` in `run` | `s6-softlimit -l unlimited` | `ulimit -l unlimited` in the script; also `kern.ipc.max_locked_mem` sysctl | `launchctl limit memlock unlimited`; `SoftResourceLimits` in the plist |
| `KillMode=process` | a unit restart does not kill in-flight runbook children | OpenRC kills the main pid only by default | `sv restart` sends TERM to the main pid only | `s6-svc -r` likewise | the rc script's `stop` should signal the pid file's pid only | `launchctl` signals the process group by default; set `AbandonProcessGroup` true |
| `Nice=-5` | senses stay responsive under load | `nice -n -5` before `exec` | same | `s6-nice` or `nice` | `nice -n -5` | `Nice` key in the plist |
| `-I` on the interpreter, root-owned `/opt/microagent` | root executes nothing from a user's home | unchanged — it is the command line, not the init | unchanged | unchanged | unchanged | unchanged |

What does not change: `deploy.sh` is the only thing that knows about `systemctl`. Replace its last five lines with the equivalent enable/start for your init and write `LAST_DEPLOY` the same way so `boot_reason()` still says "deploy".

## (b) Non-systemd service detection

Service detection never used systemd. `listeners()` runs `ss -ltnpH` and reads `/proc/<pid>/comm`; health is an HTTP URL. That is the whole of SENSE for services, and it works under any init. What to change if `ss` is absent:

- `listeners()`: replace the `ss` call with `lsof -nP -iTCP -sTCP:LISTEN` or a walk of `/proc/net/tcp` + `/proc/*/fd` (inode → pid). Retain the return shape `{port: (pid, user, comm)}`; everything downstream reads only that.
- `oom_kills()`: reads `journalctl -k`. Without journald, read `dmesg` or `/var/log/kern.log` for "Killed process". Returns an integer; 0 on failure is already the fallback.
- `in_boot_grace()`: reads `/proc/uptime`. Present on every Linux.

The runbook shape (`detect|heal|verify|rollback`) is yours to fill per init; the four examples use `systemctl`, `runuser` and `docker` because those are common, not because the code expects them. `run_runbook()` only knows `/bin/sh <path> <phase>`.

## (c) cgroup v1 or no cgroups

The floor organ is the only cgroup user. `cg_floor()` begins with:

```python
if not up_on("floor") or not (CG / "cgroup.controllers").exists(): return {"on": False, "why": "flag off or no cgroup v2"}
```

`cgroup.controllers` exists only at the root of a cgroup v2 mount. On v1, or with no cgroups, the floor returns `{"on": False}`, the tick continues, and the guard degrades to `oom_score_adj` alone — which is exactly `guard()`:

```python
p = Path(f"/proc/{pid}/oom_score_adj")
cur = int(p.read_text().strip())
if cur != OOM_ADJ: p.write_text(str(OOM_ADJ))
```

That is the whole guard on a cgroup-less box: every guarded pid at -900, Micro Agent herself at -1000, and `vm.min_free_kbytes` raised. The kernel's OOM killer then takes every other process first. There is no soft reservation, so a large allocation elsewhere can still push the guarded set into swap; `stressed()` (PSI full60 ≥ 10 or under 4 GiB available) still blocks kills during that time.

If you want a v1 floor: `memory.soft_limit_in_bytes` on the v1 memory controller is the nearest cousin of `memory.low`. Replace `CG / p / "memory.low"` with `/sys/fs/cgroup/memory/<path>/memory.soft_limit_in_bytes`, read the path from the `memory:` line of `/proc/<pid>/cgroup` in `cg_of()` instead of the `0::` line, and drop the ancestor summation (v1 soft limits are not hierarchical in the same way). Retain `floor_clear()` writing the previous value back; on v1 "released" means the default `-1`, not `0`.

## (d) macOS and BSD

What is missing and what to do about each piece:

| Linux mechanism | Function | macOS / BSD substitute |
|---|---|---|
| `/proc/pressure/memory` (PSI) | `psi()` | returns `{}` when the file is missing, so `stressed()` falls back to the available-memory test only. Substitute: on macOS parse `memory_pressure -Q` ("System-wide memory free percentage") or `sysctl kern.memorystatus_level`; on FreeBSD `sysctl vm.stats.vm.v_free_count * v_page_size`. Return the same keys (`some60`, `full60`) scaled to a percent so the threshold still reads. |
| `/proc/meminfo` | `meminfo()` | returns `{}` on failure. Substitute `vm_stat` (macOS) or `sysctl hw.physmem vm.stats.vm` (FreeBSD). Return `total_gb`, `avail_gb`, `mlocked_gb`. |
| `/proc/<pid>/oom_score_adj` | `guard()` | does not exist. There is no per-process OOM priority on macOS or BSD. Disable: set `"oom_adj": null` is not supported — instead let `guard()` fail softly (it already journals `guard_error` per pid and continues) or short-circuit it with `if not Path("/proc").exists(): return []` at the top. Substitute on macOS: launchd `KeepAlive` on each guarded service's own plist so the memory-pressure killer's victim comes back. |
| `/proc/sys/vm/min_free_kbytes` | `sysctl_guard()` | returns `None` when unreadable. FreeBSD: `vm.v_free_min` is read-only at runtime; skip. macOS: no equivalent; skip. |
| cgroup v2 | `cg_floor()` | returns `{"on": False}`. No substitute; there is no soft memory reservation on either. |
| `mmap(MAP_LOCKED \| MAP_POPULATE)` | `pin()` | neither flag exists. Replace with `mmap.mmap(...)` followed by `m.madvise(mmap.MADV_WILLNEED)` and, on macOS, `mlock` via `ctypes` (`libc.mlock(addr, len)`); on FreeBSD `MAP_PREFAULT_READ` is available as a flag. Retain the `_pins` dict so a changed file is remapped. Raise `kern.ipc.max_locked_mem` / `launchctl limit memlock` first. |
| `ss -ltnpH` | `listeners()` | use `lsof -nP -iTCP -sTCP:LISTEN -FpcLn` and parse the `p`/`c`/`L`/`n` fields into the same `{port: (pid, user, comm)}`. `/proc/<pid>/comm` and `.owner()` are then unnecessary. |
| `journalctl -k` | `oom_kills()` | macOS: `log show --predicate 'eventMessage contains "memorystatus"' --last 1h`; FreeBSD: `dmesg \| grep -c "out of swap space"`. |
| `/proc/uptime` | `in_boot_grace()` | `sysctl -n kern.boottime` and subtract from now. |
| `/proc/<pid>/{fd,maps,cwd,cmdline}` | `in_use_index()` | `lsof -p` for fds, `vmmap` (macOS) / `procstat -v` (FreeBSD) for maps, `ps -o command=` for command lines. The function must still return `(paths, cmds, mounts)`. |
| `/sys/class/hwmon` | `thermal()` | returns `{}`. macOS: set `gpu_temp_command` in `config.json` to a command that prints a temperature (any sensor reader you have); FreeBSD: `sysctl -n dev.cpu.0.temperature`. |
| `fcntl.flock` | `jlog()` | present on both. Unchanged. |
| `runuser -u` | `as_user()` | use `sudo -u <user> --` or `su -m <user> -c`. One line. |
| `os.statvfs` | `df()` | present. Unchanged. |
| `rsync`, `sha256sum` | disk rule, scorecard | `rsync` ships or installs; `sha256sum` → `shasum -a 256` (macOS) or `sha256 -r` (FreeBSD). Both print `<hash>  <path>`; `remote_hashes()` parses that. |

launchd specifics: `KeepAlive` true restarts her; `RunAtLoad` true starts her at boot; a `LaunchDaemon` (in `/Library/LaunchDaemons`, root-owned) runs before any user logs in, which is the equivalent of "under the login screen". `StateDirectory` has no equivalent; create the two directories in the plist's `ProgramArguments` wrapper or leave it to the code.

Honest summary for these platforms: the journal, budgets, fail-closed, runbooks, verify, advisor gate, sanitizer, wake note, night board, scorecard, power-return and the disk rule all work unchanged. The guard loses its OOM priority, the floor is gone, the pin is best-effort. She is still a caretaker; she is a weaker shield.

## (e) Containers and Kubernetes

Two ways to run her:

**As a node daemon (DaemonSet, privileged, host PID and host network namespaces, host `/proc`, `/sys/fs/cgroup`, `/var/lib/microagent` and `/etc/microagent` mounted from the host).** This is the same as running on the host: `listeners()` sees host ports, `guard()` writes host `oom_score_adj`, `cg_floor()` writes host cgroups. The runbooks then speak to the container runtime or the kubelet (`crictl`, or `kubectl rollout restart` through a service account with exactly that verb). What she loses: nothing technical; what you must add: the privileges above, which is a decision to make with eyes open.

**As a sidecar (unprivileged, same pod as the guarded service).** She sees only the pod's network namespace and her own `/proc`. `listeners()` still works for the pod's ports. `guard()` fails per pid (`guard_error` journaled) unless the pod shares the PID namespace and she has `CAP_SYS_RESOURCE`; `sysctl_guard()` and `cg_floor()` fail or are refused by the read-only `/sys`; `pin()` works within the container's memlock limit; `oom_kills()` reads nothing. The runbooks cannot restart the sidecar's sibling container; the kubelet does that on liveness failure. What still works and is worth having: health sensing, budgets as a *record* (she will not be the one healing, but she counts the restarts she observes through `_fail` and the journal), the chained journal, the wake note into a shared volume, the sanitized mind frame, and the advisor gate for any request another session sends her. In that role she is a witness and a scribe, not a hand. Set `upgrades.json` to turn off `floor`, `thermal`, `disk` and `power_return` so the journal is not full of errors.

In either case, configuration and state should be host-persistent volumes; a sidecar whose `budget.json` dies with the pod has no memory of the storm it was just in.

## (f) Other CPU architectures

Pure Python; no compiled extension; nothing byte-order- or word-size-dependent. The file runs unchanged on x86-64, aarch64, riscv64, ppc64le. The only values that depend on the machine rather than the architecture:

- `pin_cap_bytes` (4 GiB) and `floor_max_bytes` (32 GiB) in `config.json`: size them to the box.
- `MAP_LOCKED = 0x2000` in `pin()`: a Linux constant, the same on every Linux architecture; on BSD see (d).
- `/sys/class/hwmon/*/temp1_input` in `thermal()`: present on most boards; on a board that exposes temperature elsewhere (a vendor file under `/sys/devices`, or a tool), set `gpu_temp_command` to a command that prints degrees C and the rest is unchanged.
- `ss`, `journalctl`, `rsync`, `sha256sum`: distribution packages, not architecture.
- `floor_test()` allocates 8 GiB; on a 16 GiB board it aborts by its own rule (needs ≥16 GiB available) — that is the test refusing, not failing.

## (g) A different message bus, or none

The bus is optional and off. `bus.json`:

```json
{"enabled": false, "module": "", "url": "", "token_file": "", "subject": "microagent"}
```

With `enabled: false`, `bus_presence()` returns `"off"`, nothing is imported, and the inbox is reachable only through `sudo microagent request ...` (which calls `handle_request()` directly as root). This is the shipped state and a complete one.

With `enabled: true`, `bus_presence()` does `importlib.import_module(bus.json["module"])` and expects the module to offer `await connect(url, token=..., name=..., max_reconnect_attempts=...)` returning an object with `await subscribe(subject, cb=...)`, `await publish(subject, bytes)`, `.is_closed`, and callbacks receiving a message with `.data` and `await msg.respond(bytes)`. Any client library with that shape works by name; any other shape is a ten-line adapter module you write and name in `module`. The two subjects are `<subject>.status` (request/reply: the current `status.json`) and `<subject>.request` (request/reply: the inbox, same JSON as the CLI). The token is read through `owned_file()`, so the token file must be a regular file owned by root or the service user, mode 0600.

To use something that is not request/reply (a plain HTTP endpoint, a unix socket, a file queue): write an adapter whose `connect()` returns an object whose `subscribe()` starts a listener task calling `handle_request(raw)` and whose `publish()` posts the status. `handle_request()` is the only entry point and it is synchronous and pure; it does not care how the bytes arrived.

## (h) A different model endpoint shape

One function builds every model request:

```python
def chat_request(endpoint, system, user, max_tokens=300, temperature=0.2, timeout=None):
    body = {"model": endpoint.get("model", ""), "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], **(endpoint.get("extra") or {})}
    req = urllib.request.Request(endpoint["url"], data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(endpoint.get("headers") or {})})
    with urllib.request.urlopen(req, timeout=timeout or endpoint.get("timeout", 180)) as r:
        d = json.loads(r.read())
    txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return txt.split("</think>")[-1].strip(), d.get("usage") or {}
```

`think()`, `_ask_advisor()` and `ask_advisor_about()` all call it. To speak a different wire format, change the three lines that build `body`, the line that extracts `txt`, and the `usage` return; preserve the signature `(text, usage_dict)`. Examples:

- A "prompt + response" endpoint: `body = {"model": ..., "prompt": system + "\n\n" + user, "max_tokens": ..., "temperature": ...}`; `txt = d["response"]`.
- An endpoint that wants `"options": {"num_ctx": ...}` or a `"think": "low"` key: put them in `endpoint["extra"]` in `mind.json` — they are merged into `body` already, no code change.
- An endpoint that needs a bearer token: `endpoint["headers"] = {"Authorization": "Bearer ..."}` in `mind.json` — already merged. Retain the file root-owned 0600 if you do this.
- A streaming-only endpoint: read the lines, concatenate the delta fields, return the joined text. Retain `timeout` honoured.
- A command-line model: set the advisor to `{"type": "command", "command": "..."}` — `_ask_advisor()` already supports that shape (the full prompt is passed as one argument; stdout is parsed for the JSON). For the mind, add the same three lines to `think()`.

Whatever the shape, the contract the rest of the file relies on is small: the function returns the assistant's text with any thinking block removed, or raises; the callers already handle an exception as "this endpoint did not answer" and move to the next.

## (i) Several machines — design guidance, not a feature

Micro Agent has hands on one machine. Giving her hands on a second one is not a configuration change; it is a different design, and these things would have to be true first:

1. **A fleet-wide restart budget.** Today `set_budget` (6 in 10 min) bounds the damage on one box. Across boxes, a service that depends on a service on another box can fail in a chain; two caretakers each inside their own budget can still produce twelve restarts in ten minutes between them. A shared counter — a single file on a shared mount, or a row in one of the guarded databases — that every caretaker increments before a heal and reads before deciding, with the same windows, is the minimum. `budget_ok()` is the one function to extend.
2. **A shared halt.** `HALT_HEAL` is a local file. A fleet needs one halt that every caretaker honours, written by any of them when the fleet budget trips, and released by a human in one place. Same mechanism as the shared counter; `budget_ok()` reads it first.
3. **Per-box runbooks, and only per-box runbooks.** A runbook on box A that reaches box B over ssh is a hand across a network: default-deny no longer holds, because box A cannot know what box B had under `runbooks/` at its boot. The honest shape is that each box's caretaker heals only her own box, and a cross-box need is a request on the bus to the other caretaker's inbox (`heal` verb, which lands under *her* budgets and *her* advisor gate), never a direct command.
4. **One advisor ladder, or a stated order.** If every caretaker asks the same advisor, a fleet storm becomes an advisor queue; `advisor_ready()`'s readiness file is the start of an answer (an advisor that reports `jobs > 0` is skipped), but the ordering of who asks first is a policy that does not exist yet.
5. **A wake note that says which machine.** `wake.md` is local. A session that spans machines needs the notes side by side, with the hostname in each heading; `write_wake()` would gain one field.
6. **Clock agreement.** Budgets and the night board compare timestamps; two boxes a few minutes apart will disagree about whether a job is LATE or a heal is inside its window. NTP on every box is a precondition, not a nicety.

Until those exist, the supported shape is one Micro Agent per machine, each with her own budgets, each reachable through her own inbox, and a human — or a larger model with the whole picture — reading all the wake notes. That is less than a fleet caretaker and more honest than one.
