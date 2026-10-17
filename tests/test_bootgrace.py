import json, unittest
from unittest import mock
from ma_support import ma, reset, journal, cli, scratch_home

class BootGrace(unittest.TestCase):
    def setUp(self): reset()

    def test_silent_service_in_grace_is_would_heal_only(self):
        with mock.patch.object(ma, "BOOT_GRACE_S", 10 ** 9):
            acts = ma.heal({}, held=False)
        self.assertEqual(acts, []); self.assertEqual(ma._heals, [])
        rows = journal(); kinds = [r["kind"] for r in rows]
        self.assertNotIn("heal", kinds)
        grace = [r for r in rows if r["kind"] == "would_heal" and "boot grace" in r.get("rule", "")]
        self.assertEqual(len(grace), 4)

    def test_after_grace_the_runbook_runs(self):
        with mock.patch.object(ma, "BOOT_GRACE_S", 0):
            acts = ma.heal({}, held=False)
        self.assertEqual(len(acts), 4)

    def test_hold_is_would_heal(self):
        with mock.patch.object(ma, "BOOT_GRACE_S", 0):
            self.assertEqual(ma.heal({}, held=True), [])
        self.assertTrue(all(r.get("held") for r in journal() if r["kind"] == "would_heal"))

    def test_boot_grace_from_config_file(self):
        home = scratch_home(); (home / "etc" / "config.json").write_text(json.dumps({"boot_grace_s": 10 ** 9}))
        r = cli(home, "tick", "--dry-run"); self.assertEqual(r.returncode, 0, r.stderr[-500:])
        rows = [json.loads(l) for l in (home / "state" / "journal.jsonl").read_text().splitlines()]
        self.assertTrue([x for x in rows if x["kind"] == "would_heal" and "boot grace" in x.get("rule", "")])
        self.assertFalse([x for x in rows if x["kind"] == "heal"])

if __name__ == "__main__": unittest.main()
