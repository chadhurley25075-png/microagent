import json, time, unittest
from unittest import mock
from ma_support import ma, reset, journal, SERVICES

class Budgets(unittest.TestCase):
    def setUp(self): reset()

    def test_three_heals_of_one_service_in_an_hour_marks_it_dead(self):
        t = time.time(); ma._heals[:] = [(t - 1000, "alpha"), (t - 500, "alpha"), (t - 10, "alpha")]
        ok, why = ma.budget_ok("alpha")
        self.assertFalse(ok); self.assertEqual(why, "budget: service")
        self.assertIn("alpha", json.loads(ma.DEAD_FILE.read_text()))
        ok2, why2 = ma.budget_ok("alpha"); self.assertFalse(ok2); self.assertIn("DEAD", why2)
        self.assertTrue(ma.budget_ok("beta")[0])
        self.assertIn("dead", [r["kind"] for r in journal()])

    def test_more_than_six_heals_across_the_set_in_ten_minutes_halts(self):
        t = time.time(); ma._heals[:] = [(t - 60 * i, SERVICES[i % 4]["name"]) for i in range(7)]
        ok, why = ma.budget_ok("alpha")
        self.assertFalse(ok); self.assertEqual(why, "budget: set")
        self.assertTrue(ma.HALT_HEAL.exists())
        self.assertIn("HALT_HEAL present", ma.budget_ok("delta")[1])

    def test_heals_older_than_the_window_do_not_count(self):
        t = time.time(); ma._heals[:] = [(t - 4000, "alpha"), (t - 3900, "alpha"), (t - 10, "alpha")]
        self.assertTrue(ma.budget_ok("alpha")[0])

    def test_budget_survives_a_restart(self):
        t = time.time(); ma._heals[:] = [(t - 300, "alpha"), (t - 200, "alpha"), (t - 100, "alpha")]; ma._last_heal["alpha"] = t - 100
        ma.save_budget(); ma._heals.clear(); ma._last_heal.clear()
        ma.load_budget()
        self.assertEqual(len(ma._heals), 3); self.assertIn("alpha", ma._last_heal)
        self.assertFalse(ma.budget_ok("alpha")[0])
        self.assertIn("budget_loaded", [r["kind"] for r in journal()])

    def test_heal_loop_marks_dead_after_three_runbook_heals(self):
        svc = [SERVICES[0]]
        with mock.patch.object(ma, "SERVICES", svc), mock.patch.object(ma, "BOOT_GRACE_S", 0):
            for i in range(4):
                ma._last_heal.clear(); ma._pending.clear()
                ma.heal({}, held=False)
        kinds = [r["kind"] for r in journal()]
        self.assertEqual(kinds.count("heal"), 3)
        self.assertIn("alpha", json.loads(ma.DEAD_FILE.read_text()))

    def test_heal_loop_halts_the_set(self):
        with mock.patch.object(ma, "BOOT_GRACE_S", 0):
            for i in range(3):
                ma._last_heal.clear(); ma._pending.clear()
                ma.heal({}, held=False)
        self.assertTrue(ma.HALT_HEAL.exists())
        self.assertLessEqual([r["kind"] for r in journal()].count("heal"), 7)

if __name__ == "__main__": unittest.main()
