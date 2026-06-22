import unittest


class CustomClientTests(unittest.TestCase):
    def test_sync_copies_missing_events_between_reachable_nodes(self):
        from custom.client.ddb_client import InMemoryNode, SyncClient

        node1 = InMemoryNode("node1")
        node2 = InMemoryNode("node2")
        node3 = InMemoryNode("node3")
        client = SyncClient([node1, node2, node3])

        node1.put("alpha", "one")
        node2.put("beta", "two")

        result = client.sync_all()

        self.assertEqual(result["reachable_nodes"], 3)
        self.assertEqual(node1.get("beta")["value"], "two")
        self.assertEqual(node2.get("alpha")["value"], "one")
        self.assertEqual(node3.get("alpha")["value"], "one")
        self.assertEqual(node3.get("beta")["value"], "two")

    def test_write_can_require_only_one_ack_for_two_node_outage(self):
        from custom.client.ddb_client import InMemoryNode, SyncClient

        node1 = InMemoryNode("node1")
        node2 = InMemoryNode("node2", reachable=False)
        node3 = InMemoryNode("node3", reachable=False)
        client = SyncClient([node1, node2, node3])

        result = client.put("alpha", "survivor", min_acks=1)

        self.assertEqual(result["acks"], ["node1"])
        self.assertEqual(node1.get("alpha")["value"], "survivor")

    def test_one_logical_write_reuses_one_event_across_replicas(self):
        from custom.client.ddb_client import InMemoryNode, SyncClient

        node1 = InMemoryNode("node1")
        node2 = InMemoryNode("node2")
        node3 = InMemoryNode("node3")
        client = SyncClient([node1, node2, node3])

        result = client.put("alpha", "one", min_acks=3)

        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(node1.get("alpha")["conflicts"], [])
        self.assertEqual(node2.get("alpha")["conflicts"], [])
        self.assertEqual(node3.get("alpha")["conflicts"], [])
        self.assertEqual(
            {
                node1.list_events()[0]["event_id"],
                node2.list_events()[0]["event_id"],
                node3.list_events()[0]["event_id"],
            },
            {result["events"][0]["event_id"]},
        )

    def test_quorum_write_fails_when_two_nodes_are_unreachable(self):
        from custom.client.ddb_client import InMemoryNode, SyncClient, QuorumUnavailable

        node1 = InMemoryNode("node1")
        node2 = InMemoryNode("node2", reachable=False)
        node3 = InMemoryNode("node3", reachable=False)
        client = SyncClient([node1, node2, node3])

        with self.assertRaises(QuorumUnavailable):
            client.put("alpha", "quorum", min_acks=2)

    def test_get_prefers_vector_descendant_over_lexicographically_larger_event_id(self):
        from custom.client.ddb_client import SyncClient

        class StaticNode:
            def __init__(self, node_id, state):
                self.node_id = node_id
                self.state = state

            def get(self, key):
                return self.state

            def list_events(self):
                return []

            def import_events(self, events):
                return {"inserted": 0, "ignored": 0}

        stale = {
            "key": "alpha",
            "event_id": "zzzz",
            "value": "stale",
            "vector": {"node1": 1},
            "conflicts": [],
        }
        fresh = {
            "key": "alpha",
            "event_id": "aaaa",
            "value": "fresh",
            "vector": {"node1": 1, "node2": 1},
            "conflicts": [],
        }
        client = SyncClient([StaticNode("stale", stale), StaticNode("fresh", fresh)])

        result = client.get("alpha", min_responses=2)

        self.assertEqual(result["winner"]["state"]["value"], "fresh")

    def test_get_with_repair_returns_repaired_responses(self):
        from custom.client.ddb_client import InMemoryNode, SyncClient

        node1 = InMemoryNode("node1")
        node2 = InMemoryNode("node2")
        node3 = InMemoryNode("node3")
        node1.put("alpha", "one")
        client = SyncClient([node1, node2, node3])

        result = client.get("alpha", min_responses=1, repair=True)

        self.assertEqual(len(result["responses"]), 3)
        self.assertEqual({item["state"]["value"] for item in result["responses"]}, {"one"})


if __name__ == "__main__":
    unittest.main()
