import unittest
from ma_support import ma, reset, journal

class NeverVerbs(unittest.TestCase):
    def setUp(self): reset()

    def _rb(self, name, body):
        p = ma.RUNBOOK_DIR / f"{name}.sh"; p.write_text("#!/bin/sh\n" + body + "\n"); p.chmod(0o755)

    def test_each_never_verb_is_caught(self):
        for cmd, verb in (("systemctl reboot", "reboot"), ("shutdown -h now", "shutdown"), ("poweroff", "poweroff"), ("umount -l /mnt/x", "umount"),
                          ("rm -rf /srv/x", "rm"), ("rm /tmp/lock", "rm"), ("find /srv -name x -delete", "-delete"), ("mkfs.ext4 /dev/sdz", "mkfs"),
                          ("pkill -f server", "pkill"), ("killall python3", "killall"), ("dd if=/dev/zero of=/dev/sdz", "dd if="),
                          ("docker rm -f gateway", "docker rm"), ("docker restart gateway", "docker restart"), ("shred -u f", "shred")):
            self.assertIn(verb, ma.never_verb_hits(cmd), cmd)

    def test_no_false_positives(self):
        for cmd in ("systemctl restart primary-db.service", "docker run --rm img true", "docker start gateway", "mount -a",
                    "echo confirm the form", "curl -fsS http://127.0.0.1:8081/health", "# never reboot or rm here", "x=1 # rm in a comment"):
            self.assertEqual(ma.never_verb_hits(cmd), [], cmd)

    def test_runbooks_with_never_verbs_are_refused_at_load(self):
        self._rb("bad-reboot", 'case "$1" in heal) systemctl reboot ;; esac')
        self._rb("bad-umount", 'heal() { umount /mnt/data; }\nheal')
        self._rb("bad-rm", 'case "$1" in heal) rm -f /srv/app/pid && systemctl start app ;; esac')
        self._rb("commented", '# a comment that says reboot, umount and rm -rf is not a command\ncase "$1" in heal) systemctl start app ;; esac')
        ma.load_known_runbooks()
        for bad in ("bad-reboot", "bad-umount", "bad-rm"):
            self.assertNotIn(bad, ma.KNOWN_RB); self.assertIn(bad, ma.REFUSED_RB)
            rc, why = ma.run_runbook(bad, "heal"); self.assertIsNone(rc); self.assertIn("unknown", why)
        self.assertIn("commented", ma.KNOWN_RB); self.assertIn("alpha", ma.KNOWN_RB)
        refused = [r for r in journal() if r["kind"] == "runbook_never_verb"]
        self.assertEqual(sorted(r["runbook"] for r in refused), ["bad-reboot", "bad-rm", "bad-umount"])

    def test_engine_runbook_commands_are_flagged(self):
        orig = dict(ma.ENGINE_RUNBOOKS)
        try:
            ma.ENGINE_RUNBOOKS.clear(); ma.ENGINE_RUNBOOKS["big"] = {"enabled": False, "commands": ["docker restart big-engine"]}
            ma.load_known_runbooks()
            self.assertIn("engine_runbook_never_verb", [r["kind"] for r in journal()])
        finally:
            ma.ENGINE_RUNBOOKS.clear(); ma.ENGINE_RUNBOOKS.update(orig)

    def test_builtin_value_test(self):
        self.assertTrue(ma.neververb_test()["pass"])

if __name__ == "__main__": unittest.main()
