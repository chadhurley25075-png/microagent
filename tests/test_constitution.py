import hashlib, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from ma_support import ma, reset, REPO

class Constitution(unittest.TestCase):
    def setUp(self): reset()

    def test_shipped_text_matches_the_shipped_hash(self):
        self.assertEqual(hashlib.sha256((REPO / "CONSTITUTION.md").read_bytes()).hexdigest(), ma.CONSTITUTION_SHA)
        self.assertTrue(ma.constitution_check()["ok"])
        self.assertTrue(ma.budget_ok("alpha")[0])

    def test_changed_text_blocks_heals(self):
        ma.CONSTITUTION.write_bytes(ma.CONSTITUTION.read_bytes().replace(b"I never delete", b"I may delete", 1))
        c = ma.constitution_check(); self.assertFalse(c["ok"]); self.assertIn("mismatch", c["why"])
        ok, why = ma.budget_ok("alpha"); self.assertFalse(ok); self.assertIn("CONSTITUTION", why)
        with mock.patch.object(ma, "BOOT_GRACE_S", 0):
            self.assertEqual(ma.heal({}, held=False), [])

    def test_missing_file_blocks_heals(self):
        ma.CONSTITUTION.unlink(); self.assertFalse(ma.constitution_check()["ok"])
        self.assertFalse(ma.budget_ok("alpha")[0])
        self.assertFalse(ma.pause_status()["armed"])

    def test_builtin_value_test(self):
        self.assertTrue(ma.constitution_test()["pass"])

    def test_deploy_refuses_a_mismatched_constitution(self):
        tmp = Path(tempfile.mkdtemp()); src = tmp / "repo"
        try:
            shutil.copytree(REPO, src, ignore=shutil.ignore_patterns(".git", "__pycache__", "tests"))
            ok = subprocess.run(["bash", str(src / "deploy.sh")], capture_output=True, text=True)
            self.assertNotIn("REFUSED", ok.stdout)          # the hash gate passes; a non-root run then stops at the root check
            (src / "CONSTITUTION.md").write_text((src / "CONSTITUTION.md").read_text().replace("never delete", "may delete", 1))
            bad = subprocess.run(["bash", str(src / "deploy.sh")], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2); self.assertIn("REFUSED", bad.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__": unittest.main()
