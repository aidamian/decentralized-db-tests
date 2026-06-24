import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = [
    "custom-db-base",
    "rqlite-db-base",
    "ckroch-db-base",
    "custom-db-tunnels",
    "rqlite-db-tunnels",
    "ckroch-db-tunnels",
]
BASE_PROJECTS = ["custom-db-base", "rqlite-db-base", "ckroch-db-base"]
TUNNEL_PROJECTS = ["custom-db-tunnels", "rqlite-db-tunnels", "ckroch-db-tunnels"]
DOCS_BY_PROJECT = {project: ROOT / "_docs" / f"{project}.md" for project in PROJECTS}
DB_SERVICES = {
    "custom-db-base": {
        "custom-node1": {"node1_net"},
        "custom-node2": {"node2_net"},
        "custom-node3": {"node3_net"},
    },
    "rqlite-db-base": {
        "rqlite1": {"node1_net"},
        "rqlite2": {"node2_net"},
        "rqlite3": {"node3_net"},
    },
    "ckroch-db-base": {
        "ckroch1": {"node1_net"},
        "ckroch2": {"node2_net"},
        "ckroch3": {"node3_net"},
    },
    "custom-db-tunnels": {
        "custom-node1": {"node1_net"},
        "custom-node2": {"node2_net"},
        "custom-node3": {"node3_net"},
    },
    "rqlite-db-tunnels": {
        "rqlite1": {"node1_net"},
        "rqlite2": {"node2_net"},
        "rqlite3": {"node3_net"},
    },
    "ckroch-db-tunnels": {
        "ckroch1": {"node1_net"},
        "ckroch2": {"node2_net"},
        "ckroch3": {"node3_net"},
    },
}
DB_VOLUME_TARGETS = {
    "custom-db-base": {
        "custom-node1": "/data",
        "custom-node2": "/data",
        "custom-node3": "/data",
    },
    "rqlite-db-base": {
        "rqlite1": "/rqlite/file/data",
        "rqlite2": "/rqlite/file/data",
        "rqlite3": "/rqlite/file/data",
    },
    "ckroch-db-base": {
        "ckroch1": "/cockroach/cockroach-data",
        "ckroch2": "/cockroach/cockroach-data",
        "ckroch3": "/cockroach/cockroach-data",
    },
    "custom-db-tunnels": {
        "custom-node1": "/data",
        "custom-node2": "/data",
        "custom-node3": "/data",
    },
    "rqlite-db-tunnels": {
        "rqlite1": "/rqlite/file/data",
        "rqlite2": "/rqlite/file/data",
        "rqlite3": "/rqlite/file/data",
    },
    "ckroch-db-tunnels": {
        "ckroch1": "/cockroach/cockroach-data",
        "ckroch2": "/cockroach/cockroach-data",
        "ckroch3": "/cockroach/cockroach-data",
    },
}


def compose_config(project: str) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "CLOUDFLARE_TOKEN_EXTERNAL": "test-token-external",
            "CLOUDFLARE_URL_EXTERNAL": "https://external.example.test",
            "CLOUDFLARE_TOKEN_1": "test-token-1",
            "CLOUDFLARE_URL_1": "https://node1.example.test",
            "CLOUDFLARE_TOKEN_2": "test-token-2",
            "CLOUDFLARE_URL_2": "https://node2.example.test",
            "CLOUDFLARE_TOKEN_3": "test-token-3",
            "CLOUDFLARE_URL_3": "https://node3.example.test",
        }
    )
    output = subprocess.check_output(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / project / "compose.yaml"),
            "--profile",
            "edge",
            "--profile",
            "node-direct",
            "--profile",
            "test",
            "config",
            "--format",
            "json",
        ],
        env=env,
        text=True,
    )
    return json.loads(output)


class SubprojectContractTests(unittest.TestCase):
    def test_all_projects_use_external_cloudflare_ingress_and_no_host_ports(self):
        for name in PROJECTS:
            text = (ROOT / name / "compose.yaml").read_text()
            self.assertNotIn("ports:", text, name)
            self.assertIn("cloudflared-external", text, name)
            self.assertIn("CLOUDFLARE_TOKEN_EXTERNAL", text, name)
            self.assertIn("CLOUDFLARE_URL_EXTERNAL", text, name)

    def test_base_projects_use_brokered_non_tunneled_communication(self):
        for name in BASE_PROJECTS:
            text = (ROOT / name / "compose.yaml").read_text()
            self.assertIn("event-bus", text, name)
            self.assertIn("node1_net", text, name)
            self.assertIn("node2_net", text, name)
            self.assertIn("node3_net", text, name)

    def test_tunnel_projects_use_node_cloudflare_tunnel_variables(self):
        for name in TUNNEL_PROJECTS:
            text = (ROOT / name / "compose.yaml").read_text()
            for index in (1, 2, 3):
                self.assertIn(f"CLOUDFLARE_TOKEN_{index}", text, name)
                self.assertIn(f"CLOUDFLARE_URL_{index}", text, name)

    def test_db_nodes_are_attached_only_to_their_own_node_network(self):
        for project, services in DB_SERVICES.items():
            config = compose_config(project)
            for service, expected_networks in services.items():
                with self.subTest(project=project, service=service):
                    actual_networks = set(config["services"][service].get("networks", {}))
                    self.assertEqual(actual_networks, expected_networks)
                    self.assertNotIn("ports", config["services"][service])

    def test_db_nodes_use_per_lab_worker_bind_mounts_under_volumes_root(self):
        for project, services in DB_VOLUME_TARGETS.items():
            config = compose_config(project)
            for worker_index, (service, expected_target) in enumerate(services.items(), start=1):
                with self.subTest(project=project, service=service):
                    mounts = config["services"][service].get("volumes", [])
                    self.assertTrue(mounts, f"{project}:{service} has no persistent mount")
                    matching = [
                        mount
                        for mount in mounts
                        if mount.get("target") == expected_target
                        and f"_volumes/{project}/worker{worker_index}" in mount.get("source", "")
                    ]
                    self.assertEqual(len(matching), 1, mounts)
                    self.assertEqual(matching[0].get("type"), "bind")

    def test_base_event_buses_use_per_lab_bind_mounts_under_volumes_root(self):
        for project in BASE_PROJECTS:
            config = compose_config(project)
            mounts = config["services"]["event-bus"].get("volumes", [])
            matching = [
                mount
                for mount in mounts
                if mount.get("target") == "/data"
                and f"_volumes/{project}/bus" in mount.get("source", "")
            ]
            self.assertEqual(len(matching), 1, mounts)
            self.assertEqual(matching[0].get("type"), "bind")

    def test_each_project_has_persistence_client_service(self):
        for project in PROJECTS:
            config = compose_config(project)
            self.assertIn("persistence-client", config["services"], project)
            service = config["services"]["persistence-client"]
            self.assertIn("test", service.get("profiles", []), project)
            self.assertIn("ingress_net", service.get("networks", {}), project)

    def test_persistence_scripts_have_retry_and_second_run_mode(self):
        for project in PROJECTS:
            script = (ROOT / project / "scripts" / "persistence_check.py").read_text()
            self.assertIn("REQUEST_RETRIES", script, project)
            self.assertIn("REQUIRE_PREVIOUS", script, project)

    def test_lab_docs_explain_network_isolation_topology(self):
        required_phrases = [
            "## Network Topology And Isolation",
            "no direct",
            "docker host",
            "outside world",
            "rationale",
        ]
        for project, doc in DOCS_BY_PROJECT.items():
            text = doc.read_text()
            lowered = text.lower()
            for phrase in required_phrases:
                with self.subTest(project=project, phrase=phrase):
                    if phrase.startswith("##"):
                        self.assertIn(phrase, text)
                    else:
                        self.assertIn(phrase, lowered)

    def test_tunnel_docs_explain_cloudflare_policy_failure_modes(self):
        for project in TUNNEL_PROJECTS:
            text = DOCS_BY_PROJECT[project].read_text().lower()
            with self.subTest(project=project):
                self.assertIn("1010", text)
                self.assertIn("waf", text)
                self.assertIn("access denied", text)
                if project != "custom-db-tunnels":
                    self.assertIn("websocket: bad handshake", text)

    def test_rqlite_and_cockroach_projects_use_expected_engines(self):
        self.assertIn("rqlite/rqlite", (ROOT / "rqlite-db-base" / "compose.yaml").read_text())
        self.assertIn("rqlite/rqlite", (ROOT / "rqlite-db-tunnels" / "compose.yaml").read_text())
        self.assertIn("cockroachdb/cockroach", (ROOT / "ckroch-db-base" / "compose.yaml").read_text())
        self.assertIn("cockroachdb/cockroach", (ROOT / "ckroch-db-tunnels" / "compose.yaml").read_text())

    def test_rqlite_projects_set_advertised_http_addresses(self):
        for name in ("rqlite-db-base", "rqlite-db-tunnels"):
            text = (ROOT / name / "compose.yaml").read_text()
            self.assertIn("-http-adv-addr", text, name)
            self.assertIn("-raft-adv-addr", text, name)

    def test_cockroach_base_does_not_override_single_node_listen_addr(self):
        text = (ROOT / "ckroch-db-base" / "compose.yaml").read_text()
        self.assertIn("start-single-node", text)
        self.assertNotIn("--listen-addr", text)

    def test_base_projects_do_not_use_native_peer_join(self):
        rqlite = (ROOT / "rqlite-db-base" / "compose.yaml").read_text()
        ckroch = (ROOT / "ckroch-db-base" / "compose.yaml").read_text()
        self.assertNotIn("-join", rqlite)
        self.assertNotIn("-bootstrap-expect", rqlite)
        self.assertNotIn("--join", ckroch)

    def test_base_docs_explicitly_disclaim_native_clustering(self):
        for name in ("rqlite-db-base", "ckroch-db-base"):
            text = (ROOT / name / "README.md").read_text().lower()
            self.assertIn("not", text, name)
            self.assertIn("native", text, name)
            self.assertIn("cluster", text, name)


if __name__ == "__main__":
    unittest.main()
