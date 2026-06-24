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
EXPECTED_VISIBLE_ROOT_ITEMS = EXPECTED_DIRS | {"_TODO.md"}
OPTIONAL_VISIBLE_ROOT_ITEMS = {"_volumes"}
LEGACY_DIRS = {"custom", "oss-rqlite", "scripts", "tests", "docs"}


class RepoLayoutTests(unittest.TestCase):
    def test_root_contains_only_expected_visible_directories(self):
        actual_visible = {
            path.name
            for path in ROOT.iterdir()
            if not path.name.startswith(".")
        }
        self.assertTrue(EXPECTED_VISIBLE_ROOT_ITEMS <= actual_visible)
        self.assertTrue(actual_visible <= EXPECTED_VISIBLE_ROOT_ITEMS | OPTIONAL_VISIBLE_ROOT_ITEMS)

    def test_legacy_root_files_and_directories_are_absent(self):
        for name in LEGACY_DIRS | {"README.md"}:
            self.assertFalse((ROOT / name).exists(), name)

    def test_canonical_todo_and_local_volumes_are_ignored_but_present(self):
        self.assertTrue((ROOT / "_TODO.md").exists())
        gitignore = (ROOT / ".gitignore").read_text()
        self.assertIn("_TODO.md", gitignore)
        self.assertIn("_volumes/", gitignore)
        volumes = ROOT / "_volumes"
        if volumes.exists():
            self.assertTrue(volumes.is_dir())

    def test_each_subproject_is_self_contained(self):
        for name in EXPECTED_DIRS - {"_docs"}:
            project = ROOT / name
            self.assertTrue((project / "compose.yaml").exists(), name)
            self.assertTrue((project / "README.md").exists(), name)
            self.assertTrue((project / "scripts" / "verify.sh").exists(), name)
            self.assertTrue((project / "scripts" / "persistence_check.py").exists(), name)


if __name__ == "__main__":
    unittest.main()
