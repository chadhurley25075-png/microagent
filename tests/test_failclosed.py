import unittest
from unittest import mock
from ma_support import ma, reset, journal

class FailClosed(unittest.TestCase):
    def setUp(self): reset()

    def test_corrupt_budget_file_at_load(self):
        ma.BUDGET_FILE.write_bytes(b"\x00corrupt{{{not json")
        ma.load_budget()
        self.assertTrue(ma.FAIL_CLOSED.exists()); self.assertTrue(ma.HALT_HEAL.exists())
        ok, why = ma.budget_ok("alpha"); self.assertFalse(ok)
        self.assertIn("fail_closed", [r["kind"] for r in journal()])

    def test_corrupt_dead_services_file(self):
        ma.DEAD_FILE.write_text("{not json")
        ok, why = ma.budget_ok("alpha")
        self.assertFalse(ok); self.assertIn("FAIL-CLOSED", why); self.assertTrue(ma.FAIL_CLOSED.exists())

    def test_corrupt_fail_closed_file_is_still_closed(self):
        ma.FAIL_CLOSED.write_bytes(b"\xff\xfe garbage")
        self.assertTrue(ma.fail_closed_why())
        self.assertFalse(ma.budget_ok("alpha")[0])

    def test_corrupt_halt_file_is_still_a_halt(self):
        ma.HALT_HEAL.write_bytes(b"\x00\x01")
        ok, why = ma.budget_ok("alpha"); self.assertFalse(ok); self.assertIn("HALT_HEAL", why)

    def test_no_heal_runs_while_fail_closed(self):
        ma.BUDGET_FILE.write_text("[[[["); ma.load_budget()
        with mock.patch.object(ma, "BOOT_GRACE_S", 0):
            acts = ma.heal({}, held=False)
        self.assertEqual(acts, []); self.assertNotIn("heal", [r["kind"] for r in journal()])

if __name__ == "__main__": unittest.main()
