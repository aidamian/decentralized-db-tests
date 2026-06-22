import tempfile
import unittest
from pathlib import Path


class CustomStoreTests(unittest.TestCase):
    def test_local_write_records_event_and_materialized_value(self):
        from custom.node.store import EventStore

        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore("node1", Path(tmp) / "node.db")

            event = store.local_put("alpha", {"count": 1}, actor="client-a")

            self.assertEqual(event["origin_node"], "node1")
            self.assertEqual(event["origin_seq"], 1)
            self.assertEqual(event["vector"], {"node1": 1})
            self.assertEqual(store.get("alpha")["value"], {"count": 1})
            self.assertEqual(store.list_events()[0]["event_id"], event["event_id"])

    def test_importing_the_same_event_is_idempotent(self):
        from custom.node.store import EventStore

        with tempfile.TemporaryDirectory() as tmp:
            source = EventStore("node1", Path(tmp) / "source.db")
            target = EventStore("node2", Path(tmp) / "target.db")
            event = source.local_put("alpha", "one", actor="client-a")

            first = target.import_events([event])
            second = target.import_events([event])

            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(target.get("alpha")["value"], "one")
            self.assertEqual(len(target.list_events()), 1)

    def test_concurrent_events_preserve_conflict_metadata(self):
        from custom.node.store import EventStore

        with tempfile.TemporaryDirectory() as tmp:
            node1 = EventStore("node1", Path(tmp) / "node1.db")
            node2 = EventStore("node2", Path(tmp) / "node2.db")
            event1 = node1.local_put("alpha", "from-node1", actor="client-a")
            event2 = node2.local_put("alpha", "from-node2", actor="client-b")

            node1.import_events([event2])
            node2.import_events([event1])

            state1 = node1.get("alpha")
            state2 = node2.get("alpha")
            self.assertEqual(state1["value"], state2["value"])
            self.assertEqual(state1["conflicts"], state2["conflicts"])
            self.assertEqual(len(state1["conflicts"]), 1)
            self.assertEqual(
                {state1["value"], state1["conflicts"][0]["value"]},
                {"from-node1", "from-node2"},
            )

    def test_three_way_concurrent_events_converge_with_canonical_conflict_order(self):
        from custom.node.store import EventStore

        with tempfile.TemporaryDirectory() as tmp:
            node1 = EventStore("node1", Path(tmp) / "node1.db")
            node2 = EventStore("node2", Path(tmp) / "node2.db")
            node3 = EventStore("node3", Path(tmp) / "node3.db")
            event1 = node1.local_put("alpha", "one", actor="client-a")
            event2 = node2.local_put("alpha", "two", actor="client-b")
            event3 = node3.local_put("alpha", "three", actor="client-c")

            node1.import_events([event2, event3])
            node2.import_events([event3, event1])
            node3.import_events([event1, event2])

            states = [node.get("alpha") for node in (node1, node2, node3)]
            conflict_ids = [
                [conflict["event_id"] for conflict in state["conflicts"]]
                for state in states
            ]
            self.assertEqual(states[0]["event_id"], states[1]["event_id"])
            self.assertEqual(states[1]["event_id"], states[2]["event_id"])
            self.assertEqual(conflict_ids[0], conflict_ids[1])
            self.assertEqual(conflict_ids[1], conflict_ids[2])
            self.assertEqual(conflict_ids[0], sorted(conflict_ids[0]))
            self.assertEqual(
                {states[0]["event_id"], *conflict_ids[0]},
                {event1["event_id"], event2["event_id"], event3["event_id"]},
            )

    def test_follow_up_write_dominates_all_locally_known_conflicts(self):
        from custom.node.store import EventStore

        with tempfile.TemporaryDirectory() as tmp:
            node1 = EventStore("node1", Path(tmp) / "node1.db")
            node2 = EventStore("node2", Path(tmp) / "node2.db")
            event1 = node1.local_put("alpha", "one", actor="client-a")
            event2 = node2.local_put("alpha", "two", actor="client-b")
            node1.import_events([event2])

            merged = node1.local_put("alpha", "merged", actor="client-a")
            node2.import_events([event1, merged])

            self.assertEqual(node1.get("alpha")["value"], "merged")
            self.assertEqual(node1.get("alpha")["conflicts"], [])
            self.assertEqual(node2.get("alpha")["value"], "merged")
            self.assertEqual(node2.get("alpha")["conflicts"], [])
            self.assertEqual(merged["vector"], {"node1": 2, "node2": 1})


if __name__ == "__main__":
    unittest.main()
