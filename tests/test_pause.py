import json, signal, subprocess, sys, time, unittest
from pathlib import Path
from unittest import mock
from ma_support import ma, reset, journal

def _child():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    for _ in range(50):
        try:
            if Path(f"/proc/{p.pid}/comm").read_text().strip().startswith("python"): break
        except Exception: pass
        time.sleep(0.02)
    return p

class PauseReflex(unittest.TestCase):
    """law 11: SIGSTOP, ask, SIGCONT. The reflex never kills on silence or on a deny. os.kill is mocked: no signal reaches any process."""
    def setUp(self):
        reset(); self.p = _child()
        comm = Path(f"/proc/{self.p.pid}/comm").read_text().strip()
        self.pick = {"pid": self.p.pid, "comm": comm, "rss_mb": 300, "uid": 1000, "cmd": "python -c sleep", "start": ma._starttime(self.p.pid)}
    def tearDown(self):
        self.p.kill(); self.p.wait()

    def _run(self, advisor, test=True):
        with mock.patch.object(ma, "DRY", False), mock.patch.object(ma.os, "kill") as k, mock.patch.object(ma, "notify") as n:
            rec = ma.pause_act(self.pick, "drill", deadline=0.3, advisor=advisor, test=test, poll_s=0.05)
        return rec, [c.args[1] for c in k.call_args_list], n

    def test_silence_resumes_and_never_kills(self):
        rec, sigs, _ = self._run(lambda k, q: None)
        self.assertEqual(rec["act"], "resumed_silence")
        self.assertEqual(sigs, [signal.SIGSTOP, signal.SIGCONT])
        self.assertNotIn(signal.SIGKILL, sigs); self.assertNotIn(signal.SIGTERM, sigs)

    def test_deny_resumes_and_never_kills(self):
        rec, sigs, _ = self._run(lambda k, q: {"verdict": "deny", "advisor": "stub"})
        self.assertEqual(rec["act"], "resumed_deny"); self.assertEqual(sigs, [signal.SIGSTOP, signal.SIGCONT])

    def test_garbage_verdict_is_not_a_yes(self):
        rec, sigs, _ = self._run(lambda k, q: {"verdict": "sure, kill it"})
        self.assertNotIn(signal.SIGKILL, sigs); self.assertNotIn(signal.SIGTERM, sigs)

    def test_only_an_approve_reaches_a_kill(self):
        with mock.patch.object(ma.time, "sleep"):
            rec, sigs, _ = self._run(lambda k, q: {"verdict": "approve", "advisor": "stub"})
        self.assertEqual(rec["act"], "killed"); self.assertEqual(sigs[0], signal.SIGSTOP); self.assertIn(signal.SIGTERM, sigs)

    def test_live_silence_escalates_and_records(self):
        rec, sigs, n = self._run(lambda k, q: None, test=False)
        self.assertTrue(rec["escalated"]); self.assertTrue(n.called); self.assertNotIn(signal.SIGKILL, sigs)
        self.assertEqual(json.loads(ma.PAUSE_FILE.read_text())["last"]["act"], "resumed_silence")

    def test_real_stop_and_continue_on_our_own_child(self):
        """Real signals on a child of this test: only SIGSTOP and SIGCONT may pass; anything else fails the test before it is sent."""
        import os, threading
        real_kill = os.kill; seen = []
        def guard(pid, sig):
            seen.append(sig)
            if pid != self.p.pid or sig not in (signal.SIGSTOP, signal.SIGCONT): raise AssertionError(f"forbidden signal {sig} to {pid}")
            real_kill(pid, sig)
        state = {}
        def ask(k, q):
            state.setdefault("during", Path(f"/proc/{self.p.pid}/stat").read_text().split(")")[-1].split()[0]); return None
        with mock.patch.object(ma, "DRY", False), mock.patch.object(ma.os, "kill", guard), mock.patch.object(ma, "notify"):
            rec = ma.pause_act(self.pick, "drill", deadline=0.3, advisor=ask, test=True, poll_s=0.05)
        after = Path(f"/proc/{self.p.pid}/stat").read_text().split(")")[-1].split()[0]
        self.assertEqual(state["during"], "T"); self.assertIn(after, ("S", "R")); self.assertEqual(seen, [signal.SIGSTOP, signal.SIGCONT])
        self.assertEqual(rec["act"], "resumed_silence")

    def test_a_changed_pid_gets_no_signal(self):
        self.pick["comm"] = "someone-else"
        rec, sigs, _ = self._run(lambda k, q: {"verdict": "approve"})
        self.assertEqual(rec["act"], "skipped"); self.assertEqual(sigs, [])

    def test_dry_run_sends_nothing(self):
        with mock.patch.object(ma.os, "kill") as k:
            rec = ma.pause_act(self.pick, "drill", deadline=0.1, advisor=lambda k, q: {"verdict": "approve"})
        self.assertEqual(rec["act"], "would_pause"); self.assertFalse(k.called)

class PauseCandidates(unittest.TestCase):
    def setUp(self): reset()

    def test_exclusions(self):
        ex = ma._exclusion
        self.assertIn("guarded", ex(10, 1000, "x", "x", "", {10}))
        self.assertEqual(ex(11, 0, "x", "x", "", set()), "root-owned")
        self.assertIn("system account", ex(12, 500, "x", "x", "", set()))
        self.assertEqual(ex(13, 1000, "x", "x", "system.slice/docker-abc.scope", set()), "container")
        self.assertIn("never-pause", ex(14, 1000, "sshd", "sshd: x", "", set()))
        self.assertIsNone(ex(15, 1000, "python3", "python3 bench.py", "", set()))
        with mock.patch.object(ma, "ENGINE_MARKS", ("serve-model",)):
            self.assertIn("engine mark", ex(16, 1000, "python3", "python3 serve-model --port 9", "", set()))
        with mock.patch.object(ma, "PAUSE_SEAT_COMMS", {"assistant"}):
            self.assertEqual(ex(17, 1000, "assistant", "assistant", "", set()), "interactive assistant seat")
            self.assertIsNone(ex(18, 1000, "assistant", "assistant -p do-a-batch-job", "", set()))

    def test_ranking_on_the_live_process_table_excludes_root_and_me(self):
        with mock.patch.object(ma, "up_val", lambda k: 0 if k == "pause_min_rss_mib" else ma.UP_TUNE[k]):
            rows = ma.pause_candidates(ls={})
        import os
        self.assertTrue(all(r["excluded"] for r in rows if r["uid"] == 0))
        me = [r for r in rows if r["pid"] == os.getpid()]
        self.assertTrue(me and me[0]["excluded"])

    def test_disarmed_under_hold(self):
        ma.HOLD.write_text("{}")
        self.assertFalse(ma.pause_status()["armed"])

    def test_sandbox_budget_is_bounded(self):
        G = ma.GIB
        high, mx = ma.sandbox_budget(avail_gb=40, usage_b=0, floor_gb=10)   # 40 - 10 - 8 reserve = 22; 40 - 16 box = 24 → 22
        self.assertEqual(high, 22 * G); self.assertEqual(mx, 26 * G)
        high, mx = ma.sandbox_budget(avail_gb=5, usage_b=0, floor_gb=10)    # never under sandbox_min (8)
        self.assertEqual(high, 8 * G)

if __name__ == "__main__": unittest.main()
