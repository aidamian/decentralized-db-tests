from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASE_PROJECTS = ["custom-db-base", "rqlite-db-base", "ckroch-db-base"]


class BrokeredQueryReplyTests(unittest.TestCase):
    def test_relays_publish_query_results_to_payload_reply_inbox(self):
        for project in BASE_PROJECTS:
            relay = ROOT / project / "brokered" / "relay.py"
            text = relay.read_text()
            self.assertIn('await nc.publish(payload["reply"]', text, project)
            self.assertNotIn("await msg.respond(", text, project)

    def test_clients_default_timeout_exceeds_gateway_ack_window(self):
        for project in BASE_PROJECTS:
            client = (ROOT / project / "brokered" / "client.py").read_text()
            gateway = (ROOT / project / "brokered" / "gateway.py").read_text()
            self.assertIn('API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "30"))', client, project)
            self.assertIn('ACK_TIMEOUT_SECONDS = float(os.environ.get("ACK_TIMEOUT_SECONDS", "10"))', gateway, project)
            self.assertIn("await nc.close()", gateway, project)
            self.assertNotIn("await nc.drain()", gateway, project)


if __name__ == "__main__":
    unittest.main()
