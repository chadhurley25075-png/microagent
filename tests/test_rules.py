import json, unittest
from ma_support import ma, reset, cli, scratch_home

class TightenOnly(unittest.TestCase):
    def setUp(self): reset()

    def test_deny_a_verb(self):
        ok, msg = ma.rules_deny("verb", "heal"); self.assertTrue(ok, msg)
        self.assertNotIn("heal", ma.verbs_active())
        r = ma.handle_request(json.dumps({"verb": "heal", "args": {"service": "alpha"}, "from": "test"}))
        self.assertFalse(r["ok"])

    def test_deny_a_runbook(self):
        ma.rules_deny("runbook", "alpha")
        rc, why = ma.run_runbook("alpha", "heal")
        self.assertIsNone(rc); self.assertIn("denied at runtime", why)

    def test_widening_is_refused(self):
        ok, msg = ma.rules_widen_refused("verb", "shell"); self.assertFalse(ok); self.assertIn("REFUSED", msg)
        ok2, _ = ma.rules_deny("verb", "not-a-verb"); self.assertFalse(ok2)

    def test_silently_removed_deny_is_reported_as_tamper(self):
        ma.rules_deny("runbook", "beta"); ma.rules_deny("verb", "standing")
        self.assertEqual(ma.rules_tamper(), [])
        d = json.loads(ma.RULES_DENY.read_text()); d["runbooks"] = []; ma.RULES_DENY.write_text(json.dumps(d))
        gone = ma.rules_tamper()
        self.assertEqual(len(gone), 1); self.assertIn("beta", gone[0])
        self.assertNotIn("beta", ma.denied()[1])

    def test_cli_verify_fails_on_a_widened_rule(self):
        home = scratch_home(); etc = home / "etc"
        r = cli(home, "rules", "deny", "runbook", "gamma"); self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(cli(home, "verify").returncode, 0)
        (etc / "rules_deny.json").write_text(json.dumps({"verbs": [], "runbooks": []}))
        bad = cli(home, "verify"); self.assertEqual(bad.returncode, 1)
        self.assertTrue(json.loads(bad.stdout)["rules_widened_outside_deploy"])

if __name__ == "__main__": unittest.main()
