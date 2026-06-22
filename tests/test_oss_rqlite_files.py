import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RqliteLabFilesTests(unittest.TestCase):
    def test_rqlite_compose_defines_three_nodes_with_no_host_ports(self):
        text = (ROOT / "oss-rqlite" / "compose.yaml").read_text()

        for node in ("rqlite1", "rqlite2", "rqlite3"):
            self.assertIn(f"{node}:", text)
            self.assertIn(f"{node}_data:", text)
        self.assertIn("rqlite-client:", text)
        self.assertIn("profiles: [\"test\"]", text)
        self.assertNotIn("ports:", text)
        self.assertIn("rqlite/rqlite:10.2.1", text)
        self.assertIn("-bootstrap-expect", text)
        self.assertIn("-join", text)

    def test_rqlite_client_and_verification_script_exist(self):
        expected = [
            ROOT / "oss-rqlite" / "client" / "Dockerfile",
            ROOT / "oss-rqlite" / "client" / "scenario.py",
            ROOT / "scripts" / "rqlite_verify_constraints.sh",
            ROOT / "scripts" / "rqlite_verify_quorum.sh",
            ROOT / "docs" / "oss-cloudflare-tcp-overlay.md",
        ]
        for path in expected:
            self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
