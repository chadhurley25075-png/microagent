# Runbooks

A runbook is how Micro Agent's hand touches a service. She never improvises a command; she runs a script you wrote, by name, with one argument, and reads the exit code.

## The format

- Path: `/etc/microagent/runbooks/<name>.sh`. The `<name>` is what `services.json` names in `"runbook"`.
- Ownership: root, mode 0755 or tighter (no group or world write). She checks this at every run and refuses otherwise.
- Presence: the file must exist when she starts. `load_known_runbooks()` lists the directory once at boot; a name not in that list is unknown and denied, including for the kill path (no kill either, since the kill is only ever followed by a runbook). Add a runbook, restart her.
- Invocation: `/bin/sh /etc/microagent/runbooks/<name>.sh <phase>` as root, 120 s timeout, output captured. The last 300 characters are journaled after sanitizing.
- Phases, by the single argument:

| Phase | When she calls it | Must do | Exit |
|---|---|---|---|
| `detect` | Never by the tick (she senses ports and health herself); for your own testing and for operators | Report whether the service is healthy right now; change nothing | 0 = healthy |
| `heal` | Port silent (certain case); after an advisor-approved exact-pid kill; after an advisor-approved residue verdict; for an approved inbox `heal` | Bring the service back, idempotently | 0 = started |
| `verify` | 5 s after every `heal`, in a thread (`verify_at()`) | Confirm it really answers; wait what it needs | 0 = healthy |
| `rollback` | When the +5 s verify fails | Undo whatever `heal` did that could make things worse; never delete data | 0 = done or nothing to undo |

Her own verify (port listening + health URL) runs alongside yours at +5 s and again on the next tick (≥60 s). Both are journaled: `heal_verified_5s` and `heal_verified`.

What a runbook must never do: delete; kill by name (`pkill -f`, `killall`); restart a running engine; touch another unit, the network, or mounts; print a secret; use `set -e` in a way that exits before the right code is set.

Never-verbs are refused at load. Every runbook file is read as text when she starts; comments are dropped; a runbook whose remaining text carries `reboot`, `shutdown`, `poweroff`, `kexec`, `umount`, `mkfs`, `wipefs`, `fdisk`, `parted`, `pkill`, `killall`, `rm`, `rmdir`, `shred`, `unlink`, `-delete`, `truncate`, `dd if=`, `docker rm|kill|stop|restart`, `drop database|table` (the full list is in ARCHITECTURE.md) is journaled `runbook_never_verb` and treated as unknown. A comment may say "never reboot"; a command may not reboot. A stale pid file is the service's own supervisor's job, never `rm` in a runbook.

Runtime denial: `sudo microagent rules deny runbook <name>` stops her from running it until the next deploy. It cannot be re-allowed at runtime; that is by design.

## The four examples

### `primary-db` — a database behind a systemd unit

The simplest shape. `heal` is `systemctl restart` if active, `systemctl start` if not. `verify` waits 2 s and runs the readiness command. `rollback` clears a failed unit state with `systemctl reset-failed` so the unit's own `Restart=` policy is not stuck, and says there is nothing else to undo. The service's data directory is never named in the script. Edit `UNIT`, `PORT`, `HEALTH_CMD`.

### `search-index` — a user-level process started by its own command

For a service that is not a unit: `heal` first checks whether the port is already busy and, if so, exits 0 without starting a second copy — a listening-but-sick process is Micro Agent's decision (exact-pid kill after an advisor's yes), never the runbook's. Only when the port is silent does it start the process as `SERVICE_USER` through `runuser`, with `nohup` and a log. `verify` waits 3 s and reads the health URL. `rollback` has nothing to undo and points at the log. Edit `SERVICE_USER`, `PORT`, `START`, `HEALTH`.

### `embedder` — a slow starter

An embedding server loads a model before it answers. `heal` is a unit restart; `verify` polls the health URL up to 10 times, 2 s apart, so a cold start of 20 s still passes. Micro Agent's +60 s check covers anything slower. `rollback` clears the failed state. This is the pattern for anything with a warm-up: make `verify` patient rather than making `heal` clever.

### `gateway` — a container

`heal` distinguishes the two cases a container can be in. Not running → `docker start`, which cannot hurt anything that is serving. Running but silent → print "running but silent: a wedge, not a start — needs a human" and exit 3. A running engine is never restarted by a runbook; if it must die, that is the exact-pid path with the advisor's yes, and if it is a wedge that a signal cannot fix, that is a human. `verify` waits 5 s for the container's own health. `rollback` points at `docker logs`.

## Writing your own

Copy the example closest to your service, change the variables at the top, hold the four phases, hold the refusals. Test every phase by hand as root before she ever runs it:

```sh
for p in detect heal verify rollback; do sudo sh /etc/microagent/runbooks/<name>.sh $p; echo "$p -> $?"; done
sudo chown root:root /etc/microagent/runbooks/<name>.sh && sudo chmod 0755 /etc/microagent/runbooks/<name>.sh
sudo systemctl restart microagent && sleep 3 && microagent journal 5     # the "runbooks" line must list it as known, missing = [] and refused_never_verb = []
```

A full prompt for an assistant writing runbooks is in AGENTS.md (d).

## Engine runbooks — the shadow table

`engine_runbooks.json` holds runbooks for things that are too large or too consequential to wire to a hand yet: a model engine across several processes, a cluster, anything whose restart has preconditions a script cannot check. The table ships empty. An entry is a description, not a script:

```json
{
  "engine-restart-clean": {
    "enabled": false,
    "engine": "what it is",
    "law": "the rule that governs restarting it",
    "trigger": "the exact evidence that would justify it",
    "gates": ["advisor approve", "HOLD for the whole run", "restart budget ≤1 per 6 h", "idle ≥15 min since its last job", "memory ≥16 GB free"],
    "commands": ["the commands, in order, that WOULD run"],
    "verify": "what proves it worked at 5 s and at 60 s",
    "can_be_safe_behind": "an honest answer about which case is safe behind the gates and which is not",
    "needs_human": ["every case where no verb reaches the fix: a stuck link, a power button, a judgment about work in progress"]
  }
}
```

`microagent engine-runbook <name> --dry-run` prints it. `microagent engine-runbook <name>` without `--dry-run` refuses, journals the refusal, and exits non-zero. `enabled` is read and reported but no code path acts on it: enabling an engine runbook means writing a real runbook script, listing the engine in `services.json`, and a deploy. The table exists so that the honest analysis — what is safe, what is not, what still needs a person — is written down before anyone is tempted to automate it.
