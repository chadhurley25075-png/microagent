import json, unittest
from ma_support import ma, reset, journal, cli, scratch_home

class JournalChain(unittest.TestCase):
    def setUp(self): reset()

    def test_lines_chain_to_the_line_before(self):
        for i in range(5): ma.jlog("test_event", n=i)
        n, first, breaks = ma.verify_chain()
        self.assertGreaterEqual(n, 5); self.assertEqual(first, 1); self.assertEqual(breaks, [])
        rows = journal(); self.assertEqual(rows[0]["prev"], "genesis")
        self.assertTrue(all(r["dry"] for r in rows))

    def test_a_tampered_line_is_detected(self):
        for i in range(5): ma.jlog("test_event", n=i)
        lines = ma.JOURNAL.read_text().splitlines()
        rec = json.loads(lines[2]); rec["n"] = 99; lines[2] = json.dumps(rec)
        ma.JOURNAL.write_text("\n".join(lines) + "\n")
        n, first, breaks = ma.verify_chain()
        self.assertIn((4, "prev mismatch"), breaks)

    def test_a_removed_line_is_detected(self):
        for i in range(5): ma.jlog("test_event", n=i)
        lines = ma.JOURNAL.read_text().splitlines(); del lines[1]
        ma.JOURNAL.write_text("\n".join(lines) + "\n")
        self.assertTrue(ma.verify_chain()[2])

    def test_cli_verify_exit_codes(self):
        home = scratch_home()
        self.assertEqual(cli(home, "lesson-test").returncode, 0)          # writes a few chained lines
        ok = cli(home, "verify"); self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["ok"])
        j = home / "state" / "journal.jsonl"; lines = j.read_text().splitlines()
        lines[0] = lines[0].replace('"drill-unit"', '"drill-unot"'); j.write_text("\n".join(lines) + "\n")
        bad = cli(home, "verify"); self.assertEqual(bad.returncode, 1); self.assertFalse(json.loads(bad.stdout)["ok"])

if __name__ == "__main__": unittest.main()
