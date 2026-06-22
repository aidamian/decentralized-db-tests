import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CustomLabFilesTests(unittest.TestCase):
    def test_custom_compose_has_three_isolated_nodes_and_no_published_ports(self):
        compose_path = ROOT / "custom" / "compose.yaml"
        text = compose_path.read_text()

        self.assertIn("custom-node1:", text)
        self.assertIn("custom-node2:", text)
        self.assertIn("custom-node3:", text)
        self.assertIn("custom-client:", text)
        self.assertNotIn("ports:", text)
        self.assertIn("custom_node1_net:", text)
        self.assertIn("custom_node2_net:", text)
        self.assertIn("custom_node3_net:", text)
        self.assertIn("profiles: [\"test\"]", text)

    def test_cloudflare_override_uses_token_file_secrets_not_command_line_tokens(self):
        compose_path = ROOT / "custom" / "compose.cloudflare.yaml"
        text = compose_path.read_text()
        runner_text = (ROOT / "custom" / "node" / "run-node.sh").read_text()

        for index in (1, 2, 3):
            self.assertIn(f"CLOUDFLARE_URL_{index}", text)
            self.assertIn(f"cf_token_{index}", text)
        self.assertIn("--token-file", runner_text)
        self.assertNotIn("--token ${CLOUDFLARE_TOKEN", text)

    def test_custom_dockerfiles_and_verification_script_exist(self):
        expected = [
            ROOT / "custom" / "node" / "Dockerfile",
            ROOT / "custom" / "node" / "run-node.sh",
            ROOT / "custom" / "client" / "Dockerfile",
            ROOT / "scripts" / "custom_verify_constraints.sh",
        ]
        for path in expected:
            self.assertTrue(path.exists(), path)


if __name__ == "__main__":
    unittest.main()
