# A caretaker below the OS

What a small root-level agent can do when it lives under every login and every assistant session, mechanism by mechanism; what it cannot do no matter how much privilege it has; and where this design could go. Everything in the first two parts is implemented in `microagent.py` unless marked otherwise.

## Why "below"

An assistant session is a guest. It arrives when someone opens a terminal, it leaves when they close it, and in between it sees the machine through the tools it was handed. The services it depends on — the memory store, the index, the embedding server — were started by something else and will be restarted, or not, by something else. When they die at 3 a.m., nobody is there.

A caretaker below the login is the thing that is there. It starts when the kernel finishes, as root, with no terminal and no human, and it holds one small promise: the named services stay alive, the hot files stay in RAM, and when the next session opens there is a note saying what happened. Being root is not the interesting part; being *present* is. Root is what makes the promise keepable, and it is also the reason every verb she has is small.

## Process guardianship

**`oom_score_adj`.** The kernel's OOM killer picks the process with the highest `oom_score`, which is memory use adjusted by `/proc/<pid>/oom_score_adj` in [-1000, 1000]. Writing -900 to a guarded pid makes it the last candidate but not immune (-1000 would be immune, which is the wrong choice for anything but the caretaker herself: an immune process that leaks can take the machine down with it). Micro Agent writes -900 to every guarded pid every tick (`guard()`), skips `docker-proxy` pids (the container is the service), and runs herself at -1000 through the unit. Cost: one read and sometimes one write per pid per 5 minutes.

**cgroup v2 `memory.low` and `memory.min`.** `memory.low` is a soft reservation: under pressure the kernel reclaims every cgroup *without* protection first, and touches a protected cgroup only when nothing else is left. `memory.min` is hard: the kernel will not reclaim below it even if that means OOM-killing something else. Micro Agent uses only `memory.low` (`cg_floor()`), sized from live RSS × 1.25, quantised to 64 MiB, capped at 32 GiB total, and written on the leaf and every ancestor (with `memory_recursiveprot`, an ancestor's `low` caps its children, so the sum must flow up). Why not `min`: a hard floor on a set of services that together exceed free memory starves everything else and the box dies with the services alive — the wrong trade. Why not move pids into a dedicated cgroup: moving a pid out of a systemd scope makes systemd believe the unit exited. The floor lives where the pids already are.

**PSI pressure stall signals.** `/proc/pressure/memory` reports the share of wall time some (or all) tasks spent stalled waiting on memory, averaged over 10, 60 and 300 s. `full avg60 ≥ 10` means that for 6 of the last 60 seconds *every* task was stalled — the machine is thrashing. Micro Agent reads it every tick and refuses every kill and every disk move while it is true (`stressed()`), because a restart under pressure allocates, and an allocation under pressure is how a sick box becomes a dead one. PSI is also the honest signal that `MemAvailable` is not: available memory can look fine while the page cache is being churned to nothing.

**pid-owner rechecks.** A pid is a number the kernel reuses. The pid that owned port 8081 at the top of the tick may not be the one that owns it when the advisor's answer arrives two ticks later. `_kill_exact()` re-reads the listeners at the instant of the signal and refuses if the owner changed. The same rule bars killing by name: a name matches every copy, and the copy you wanted is rarely the only one. One pid, confirmed now, or nothing.

## Memory

**mlock and mmap pinning.** A retrieval stack is only as fast as its coldest read; an index file that got evicted from the page cache turns a 2 ms lookup into a 200 ms one at the first query of the morning. `pin()` maps each named file with `MAP_SHARED | MAP_LOCKED | MAP_POPULATE`: the pages are faulted in now and cannot be swapped or evicted while the map lives. The map object is kept in a dict for the life of the process; a changed file (mtime or size) is remapped. Cap: 4 GiB by default, enforced before each map. The unit grants `LimitMEMLOCK=infinity`; the cap in `config.json` is the real limit.

**Page-cache warming vs. pinning.** Warming (reading a file once, or `madvise(MADV_WILLNEED)`) puts pages in the cache but leaves them evictable — cheap, reversible, and gone after the next large copy. Pinning holds them. The trade: pinned memory is not available to anyone else, ever, until the caretaker drops it; a 4 GiB pin on a 32 GiB box is a 12% tax paid every second for a guarantee you need a few times a day. The rule Micro Agent follows: pin the small hot core (indexes, the context file the mind reads every tick), warm nothing (the kernel does that well on its own), and retain the cap honest.

**Reservation vs. pinning.** `memory.low` reserves for a *process* without naming files; `mlock` pins *files* without naming a process. They answer different questions. A guarded service that allocates its working set anew each start wants the reservation; a file that many processes read wants the pin. Both together: the service holds its heap under pressure, and the file it reads stays in RAM for the new process after a restart — which is the case that matters, because a restart is exactly when the cache would otherwise be cold.

**`vm.min_free_kbytes`.** The kernel holds this much memory free for atomic allocations (interrupt handlers, network receive). Too low, and a burst of network traffic under memory pressure fails inside the kernel; a value of 1 GiB on a box with 10+ GiB is a cheap margin. Micro Agent raises it if it is lower and records the old value for rollback (`sysctl_guard()`).

## Thermal and power

**hwmon.** `/sys/class/hwmon/hwmon*/temp1_input` is the CPU, NVMe, NIC and board sensors in millidegrees. Micro Agent reads them every 60 s (`thermal()`), takes the hottest, and puts it in the status and the house line. Nothing in the shipped code acts on temperature; the rungs below are design guidance for what a caretaker *could* do, in order of how much she should be trusted to do it:

| Rung | Signal | Action |
|---|---|---|
| warm | hottest sensor above its steady-state by 10 °C | journal it; mention it in the wake note |
| hot | above the vendor's throttle point | notify a human; refuse new heals (a restart adds load) |
| critical | within 5 °C of the shutdown point | ask the advisor whether to stop the largest consumer by its runbook; never a kill without the yes |
| shutdown | at the point | nothing — the firmware does it, and the caretaker's job is the power-return list afterwards |

**Power-return sequencing.** After an outage, things come back in an order that matters: the switch before the machines, the machines before their engines, the engines before the services that call them. `power_return()` probes that order in rungs and prints who answered and the manual step for who did not — a button to press, a container to start. It runs itself once after a boot that `boot_reason()` calls "power-on" (uptime < 15 min), and it only probes. The human reads the list; nothing is started by a probe.

**UPS signals (not implemented; design).** A UPS daemon exposes "on battery" and "battery low" events. The right caretaker response to "on battery" is to write `HOLD` (no heals — a restart during a brownout is a second failure waiting) and journal the time; to "battery low", to run every runbook's `verify` phase once so the journal records what was healthy at the end, and to write a wake note that says "power lost at HH:MM, these were up". Shutting the machine down is the UPS daemon's job, not hers.

## Disk

**Fill-rate forecasting (design, partly implemented).** `disks()` records percentages every tick into `status.json`; the journal holds the history. A line through the last 24 h of samples gives hours-to-full. The useful rung is not "90% now" but "90% in 36 hours at this rate" — enough time for a human. The shipped code triggers on the level; the forecast is a 20-line addition that reads its own journal.

**The never-delete posture.** Deletion is the one act with no verify phase: after it, there is nothing to check. So Micro Agent does not have the verb. The disk rule moves one cold folder, and only after copying it, hashing every file on both sides, re-listing the source to prove nothing changed during the copy, and re-checking that no process has it open — then removes the original and leaves a symlink so every path that named it still resolves. If any step doubts, both copies stay and the folder is blocked. The cost of this posture is that a full disk with nothing cold on it fills; the caretaker notifies, and a human decides what to retire. That cost is accepted on purpose.

**What "notify-only" means for an archive.** An archive of last resort is where you go when everything else failed. A caretaker that can modify it is one more thing that can fail it. So the archive path in `disks.json` is read for its percentage and nothing else; over the trigger, one notification a day and a line in the wake note. No scan, no move, no plan.

## Network

**Loopback-only binds.** Micro Agent listens on nothing. Every endpoint she calls — the mind, the advisor, each service's health URL — is on `127.0.0.1` in every shipped example, and the install prompt refuses anything else. The reason is not that the LAN is hostile; it is that a caretaker with root that answers on a network is a target, and one that only calls out to loopback has no attack surface a port scan can find.

**CGNAT-range allowance.** Overlay networks hand out addresses from the carrier-grade NAT block (the one RFC 6598 reserves). If an advisor or a backup host must live on another machine, that range is the one to allow in a firewall rule, and the honest way to use it from `advisors.json` is still a tunnel to a loopback port, so the configuration never names an address.

**No DNS in allowlists.** A name resolves to whatever the resolver says today. A configuration that allows "the advisor host" by name trusts the resolver with root's decisions. Allow by address or by tunnel endpoint; use names only for things that cannot be misused if they resolve wrong (a health probe to a machine that is not yours cannot hurt you).

## Boot order

**Grace periods.** For the first 600 s of uptime, every "silent" service is journaled `would_heal` and nothing is run (`in_boot_grace()`). Services start in their own time after boot — a database recovering its log, an index loading its file, a container runtime pulling itself up — and a caretaker that "heals" them during that window starts second copies, trips its own storm budget, and writes a journal full of noise. The right response to a slow boot is patience with a clock on it.

**Dependency rungs.** The power-return rungs are the same idea across machines: the network answers before a host is reachable, the host before its engine, the engine before a service that calls it. A caretaker that probes in that order finds where the chain broke; one that probes everything at once finds only that many things are down.

**Why healing during boot is wrong.** Three reasons, each sufficient. First, the evidence is bad: a port that is silent 40 s after boot is not a failure, it is a startup. Second, the budget is finite: three heals in an hour mark a service DEAD, and a boot can burn all three on nothing. Third, the init system already has the restart policy for each unit; a caretaker racing it produces two starters and one confused service. Boot grace is the caretaker yielding to the thing that knows the order.

## The journal

**Hash chain.** Every line carries `prev` = sha256 of the previous line's raw bytes. Alter, remove or insert a line and every later `prev` fails to match from that point. `verify_chain()` reports the first break by line number. **Tamper evidence**, not tamper proof: root can rewrite the whole file consistently. What the chain gives you is that an edit must be a rewrite, which is harder to do by accident and visible if yesterday's last hash is stored anywhere else.

**Receipts per action.** Every act is journaled *with the rule that allowed it*: `"rule": "port silent → runbook (certain)"`, `"rule": "advisor said no (advisor-large): ..."`, `"rule": "3 heals in 60 min → stop healing this service"`. Reading the journal is reading the decision, not reconstructing it. A caretaker that acts without saying why is one you cannot audit and, soon, one you do not trust.

**Two locks.** A thread lock inside the process and an `flock` on the file, because the mind thread, the advisor thread, a disk move, the house loop and a CLI invocation can all write at once, and a broken chain from a race looks exactly like a broken chain from an attacker.

## The mind

**What a sandboxed model is good for below the OS.** Explanation: turning a status dict and eight journal lines into one paragraph a tired human can read at 7 a.m. Prioritization: saying which of three things wrong matters most tonight. Proposing: "I would ask the advisor to restart the embedder" — a sentence a human can act on or ignore. The wake note is the model doing all three at once, and it is the most useful thing the mind produces.

**What it must never be given.** The shell: a model with a shell is an autonomous agent with root, which is a different and much larger project. The kill verb: a model that can name a pid can name the wrong one with perfect confidence. Unfiltered input: a model that reads a log line verbatim can be instructed by whoever wrote the log line. Micro Agent gives the mind a sanitized text frame and takes back text; the one structured answer it is asked for (`hold`/`heal`) is a suggestion that goes to the advisor, never to a hand.

**Cadence.** A model call costs seconds and electricity; a quiet machine produces the same frame every tick. The issue-set gate (`mind_due()`) calls the mind when the set of things wrong changes, or once an hour, and otherwise refreshes the wake note from rules. Two calls an hour on a quiet box; a call within one tick of anything changing.

## The advisor ladder

A kill, a restart on the mind's word, or a release of a hold goes to a larger model first. The ladder tries each configured advisor in order, skipping any whose readiness file says it is busy, held or stale, and takes the first valid `approve`/`deny`. **If no advisor answers, the answer is NO.** That default is the safety property of the whole design: every outage of the advisor, every malformed reply, every timeout, resolves to "do not act". The caretaker can only ever be *less* active than her advisors allow, never more. An advisor that says `approve` to everything makes her as active as the rules alone permit — which is still three heals an hour per service, six across the set in ten minutes, and never under memory stress.

The question is asked in a thread, and the answer is picked up on a later tick. Senses never wait on a model.

## The household line

`house.txt`, one sentence, refreshed every 60 s: *"House OK · services 5/5 · backups checked 07:12 · nothing needs you."* It has no numbers to decode and no JSON. It is for the people who share the machine's roof and not its terminal: they can read it from a phone, on a page, in a widget, and know in two seconds whether someone should look. Every other output of the caretaker is for an operator or a model; this one is for a person, and the discipline of writing it — what is true right now, in words — is a check on everything else. If the house line cannot be written honestly from the status, the status is wrong.

## Limits — what root cannot do

- **Hardware.** A stuck link, a cable, a drive that spins down, a fan that stopped. Root can read the sensor and nothing more.
- **Buttons.** A machine that does not auto-start after power needs a finger. The power-return organ prints "press the button"; that is the whole of what software can do.
- **A running-but-silent process.** A wedged engine that holds its port and answers nothing is the worst case: a signal might free it or might lose work in flight, and no reading of `/proc` says which. Micro Agent refuses it (the runbook exits 3, "needs a human") because a wrong guess costs more than a slow morning.
- **Judgment about work in progress.** Whether a service that stopped answering is dead or is 40 minutes into a batch job is not visible from outside. The advisor is asked; the advisor often cannot know either; the default is to wait.
- **Anything after a delete.** There is no verify phase for deletion, so there is no delete.

## Failure modes designed for

| Failure | Designed response |
|---|---|
| Budget file unreadable or corrupt | `FAIL_CLOSED` + `HALT_HEAL`: no heals until a human runs `release-heal`. A sick disk never disarms the storm guard. |
| Advisor down | Every major act denied; silent-port heals continue; journal shows why. |
| Mind down | Reflection skipped; wake note says so; residue judge returns `hold`; the hand is unchanged. |
| Disk full | At most one verified move per tick; nothing else; notify once a day; the archive untouched. |
| Power loss mid-heal | The service's own supervisor owns the half-done state; on power-on: boot grace, budgets reloaded from disk, power-return probes in rungs. |
| Power loss mid-move | Source untouched (removal is the last step); partial copy on the target; `rsync --partial` resumes. |
| Her own memory leaks | At 1 GiB anonymous RSS she exits 3; the init system restarts her; journal and budgets are on disk. |
| Journal edited | `verify` names the line. |
| Runbook hangs | 120 s timeout, counted as a heal, verify fails at +5 s, rollback phase runs. |

## Where this goes next — options, not promises

- **Multi-box care with a fleet budget.** One shared counter and one shared halt that every caretaker honours; each box heals only itself; cross-box needs travel as inbox requests under the other caretaker's budgets and advisor. PORTING.md (i) lists what has to be true first.
- **A tiny static binary with no interpreter.** The hand is a few hundred lines of `/proc` reads, file writes and signals; it could be a single static executable with no runtime that needs patching, started by the kernel's init line if need be. The mind and the advisor stay where they are — the binary would speak the same chat request over loopback.
- **Per-service verification hooks.** Today verify is "port + health URL + the runbook's verify phase". A richer contract — a query that must return a known row, an embedding that must match a stored vector, a write-then-read on the index — would turn "it answers" into "it is correct". The runbook format already has the phase; the examples would grow.
- **A restore drill that actually restores.** The scorecard proves the bytes match. The next rung is a nightly drill on a scratch directory: restore one backup, start the service against it, run its verify, tear it down, journal the minutes it took. A backup that has never been restored is a hope; a drill makes it a receipt.
