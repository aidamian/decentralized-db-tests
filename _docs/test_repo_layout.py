from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DIRS = {
    "_docs",
    "custom-db-base",
    "rqlite-db-base",
    "ckroch-db-base",
    "custom-db-tunnels",
    "rqlite-db-tunnels",
    "ckroch-db-tunnels",
}
LEGACY_DIRS = {"custom", "oss-rqlite", "scripts", "tests", "docs"}


class RepoLayoutTests(unittest.TestCase):
    def test_root_contains_only_expected_visible_directories(self):
        actual_visible = {
            path.name
            for path in ROOT.iterdir()
            if not path.name.startswith(".")
        }
        self.assertEqual(actual_visible, EXPECTED_DIRS)

    def test_legacy_root_files_and_directories_are_absent(self):
        for name in LEGACY_DIRS | {"README.md", "_TODO.md"}:
            self.assertFalse((ROOT / name).exists(), name)

    def test_each_subproject_is_self_contained(self):
        for name in EXPECTED_DIRS - {"_docs"}:
            project = ROOT / name
            self.assertTrue((project / "compose.yaml").exists(), name)
            self.assertTrue((project / "README.md").exists(), name)
            self.assertTrue((project / "scripts" / "verify.sh").exists(), name)


if __name__ == "__main__":
    unittest.main()
