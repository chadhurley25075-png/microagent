import time, unittest
from unittest import mock
from ma_support import ma, reset, journal

class SingleUseVerdict(unittest.TestCase):
    def setUp(self): reset()

    def test_take_verdict_states(self):
        t = 1_000_000.0
        ap = {"ts": t, "result": {"verdict": "approve", "advisor": "a"}}
        self.assertEqual(ma._take_verdict(ap, t + 1)[1], "approve consumed")
        self.assertEqual(ma._take_verdict(ap, t + 2), (None, "approve already spent"))
        dn = {"ts": t, "result": {"verdict": "deny"}}
        self.assertEqual(ma._take_verdict(dn, t + 1)[1], "deny (cached)"); self.assertEqual(ma._take_verdict(dn, t + 2)[1], "deny (cached)")
        self.assertEqual(ma._take_verdict({"ts": t, "result": None}, t + 1), (None, "asking"))
        self.assertEqual(ma._take_verdict({"ts": t, "result": {"verdict": "approve"}}, t + 901), (None, "expired"))

    def test_consult_spends_an_approve_once(self):
        key = "kill:alpha:123"
        ma._consults[key] = {"ts": time.time(), "result": {"verdict": "approve", "advisor": "stub"}}
        with mock.patch.object(ma, "ADVISORS", []):
            first = ma.consult(key, "may I?")
            second = ma.consult(key, "may I again?")
        self.assertEqual(first["verdict"], "approve")
        self.assertIsNone(second)                              # the old yes is not re-used; a fresh ask is in flight
        kinds = [r["kind"] for r in journal()]
        self.assertIn("advice_consumed", kinds); self.assertIn("advice_spent", kinds); self.assertIn("consult", kinds)

    def test_no_advisor_means_no(self):
        with mock.patch.object(ma, "ADVISORS", []):
            name, v = ma._ask_advisor("may I kill pid 1?")
        self.assertEqual(name, "none"); self.assertEqual(v["verdict"], "deny")

    def test_builtin_value_test(self):
        self.assertTrue(ma.advisor_test()["pass"])

if __name__ == "__main__": unittest.main()
