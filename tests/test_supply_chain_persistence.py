"""Tests for the isolated acknowledged persistence adapter prototype."""
import copy
import hashlib
import threading
import unittest

from supply_chain_persistence import (
    CommitOutcomeUnknown,
    IdempotencyConflict,
    PersistenceError,
    SerializedCommitAdapter,
    VersionConflict,
)


class FakeStore:
    def __init__(self):
        self.data = {"version": 1, "products": {"SKU-1": {"quantity": 5}}}
        self.fail = False
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def persist(self, candidate, expected_version, new_version):
        with self.lock:
            if self.data["version"] != expected_version:
                raise VersionConflict("database compare-and-swap failed")
            if self.fail:
                raise TimeoutError("simulated ambiguous storage timeout")
            if candidate["version"] != new_version:
                raise AssertionError("revision mismatch")
            self.data = copy.deepcopy(candidate)
            return True


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class SerializedCommitAdapterTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.adapter = SerializedCommitAdapter(self.store.load, self.store.persist)

    def change_quantity(self, amount):
        def mutate(document):
            document["products"]["SKU-1"]["quantity"] += amount
            return {"sku": "SKU-1", "quantity": document["products"]["SKU-1"]["quantity"]}
        return mutate

    def test_commit_publishes_only_after_durable_acknowledgement(self):
        result = self.adapter.commit(expected_version=1, operation_id="op-1",
                                     request_hash=digest("add-2"), mutate=self.change_quantity(2))
        self.assertEqual(result, {"version": 2, "result": {"sku": "SKU-1", "quantity": 7}, "replayed": False})
        self.assertEqual(self.store.load()["version"], 2)
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 7)
        self.assertEqual(len(self.store.load()["audit_log"]), 1)

    def test_storage_failure_leaves_committed_snapshot_unchanged(self):
        before = self.store.load()
        self.store.fail = True
        with self.assertRaises(CommitOutcomeUnknown):
            self.adapter.commit(expected_version=1, operation_id="op-fail",
                                request_hash=digest("add-2"), mutate=self.change_quantity(2))
        self.assertEqual(self.store.load(), before)

    def test_same_id_and_hash_replays_without_mutating_twice(self):
        args = dict(expected_version=1, operation_id="op-retry",
                    request_hash=digest("add-2"), mutate=self.change_quantity(2))
        first = self.adapter.commit(**args)
        second = self.adapter.commit(**args)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 7)
        self.assertEqual(self.store.load()["version"], 2)

    def test_same_id_with_different_hash_is_rejected(self):
        self.adapter.commit(expected_version=1, operation_id="op-dup",
                            request_hash=digest("payload-a"), mutate=self.change_quantity(1))
        with self.assertRaises(IdempotencyConflict):
            self.adapter.commit(expected_version=1, operation_id="op-dup",
                                request_hash=digest("payload-b"), mutate=self.change_quantity(9))
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 6)

    def test_stale_preview_version_is_rejected(self):
        self.adapter.commit(expected_version=1, operation_id="op-first",
                            request_hash=digest("one"), mutate=self.change_quantity(1))
        with self.assertRaises(VersionConflict):
            self.adapter.commit(expected_version=1, operation_id="op-stale",
                                request_hash=digest("two"), mutate=self.change_quantity(5))
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 6)

    def test_concurrent_same_version_operations_allow_only_one_commit(self):
        barrier = threading.Barrier(3)
        outcomes = []
        outcome_lock = threading.Lock()

        def worker(operation_id):
            barrier.wait()
            try:
                value = self.adapter.commit(
                    expected_version=1, operation_id=operation_id,
                    request_hash=digest(operation_id), mutate=self.change_quantity(1))
                outcome = ("committed", value["version"])
            except VersionConflict:
                outcome = ("conflict", None)
            with outcome_lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=worker, args=(f"op-{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(sum(kind == "committed" for kind, _ in outcomes), 1)
        self.assertEqual(sum(kind == "conflict" for kind, _ in outcomes), 1)
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 6)

    def test_false_ack_is_not_reported_as_success(self):
        class NoAckStore(FakeStore):
            def persist(self, candidate, expected_version, new_version):
                return False
        store = NoAckStore()
        adapter = SerializedCommitAdapter(store.load, store.persist)
        with self.assertRaises(PersistenceError):
            adapter.commit(expected_version=1, operation_id="op-noack",
                           request_hash=digest("x"), mutate=lambda doc: {"ok": True})
        self.assertEqual(store.load()["version"], 1)


if __name__ == "__main__":
    unittest.main()
