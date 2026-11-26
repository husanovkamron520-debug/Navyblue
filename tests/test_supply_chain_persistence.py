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
    SnapshotWriteQueue,
    JsonbCompareAndSwap,
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


    def test_retry_after_commit_then_timeout_replays_original_result(self):
        class CommitThenTimeoutStore(FakeStore):
            def __init__(self):
                super().__init__()
                self.first = True

            def persist(self, candidate, expected_version, new_version):
                with self.lock:
                    if self.data["version"] != expected_version:
                        raise VersionConflict("database compare-and-swap failed")
                    self.data = copy.deepcopy(candidate)
                    if self.first:
                        self.first = False
                        raise TimeoutError("response lost after database commit")
                    return True

        store = CommitThenTimeoutStore()
        adapter = SerializedCommitAdapter(store.load, store.persist)
        args = dict(expected_version=1, operation_id="op-ambiguous",
                    request_hash=digest("add-4"), mutate=lambda doc: self._add_quantity(doc, 4))
        with self.assertRaises(CommitOutcomeUnknown):
            adapter.commit(**args)
        replay = adapter.commit(**args)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["version"], 2)
        self.assertEqual(store.load()["products"]["SKU-1"]["quantity"], 9)

    def test_corrupt_matching_idempotency_record_fails_closed(self):
        self.store.data["_write_idempotency"] = [{
            "operation_id": "op-corrupt",
            "request_hash": digest("payload"),
        }]
        with self.assertRaises(PersistenceError):
            self.adapter.commit(expected_version=1, operation_id="op-corrupt",
                                request_hash=digest("payload"), mutate=self.change_quantity(1))
        self.assertEqual(self.store.load()["products"]["SKU-1"]["quantity"], 5)

    @staticmethod
    def _add_quantity(document, amount):
        document["products"]["SKU-1"]["quantity"] += amount
        return {"sku": "SKU-1", "quantity": document["products"]["SKU-1"]["quantity"]}



class SnapshotWriteQueueTests(unittest.TestCase):
    def test_newer_snapshot_is_not_replaced_when_older_inflight_write_fails(self):
        queue = SnapshotWriteQueue()
        queue.enqueue("supply_chain_data", {"version": 1})
        key, first = queue.take()
        queue.enqueue("supply_chain_data", {"version": 2})
        queue.finish(key, first, saved=False)
        self.assertEqual(queue.pending_count, 1)
        next_key, newest = queue.take()
        self.assertEqual(next_key, "supply_chain_data")
        self.assertEqual(newest, {"version": 2})
        queue.finish(next_key, newest, saved=True)
        self.assertTrue(queue.wait_empty(0.05))

    def test_wait_empty_includes_inflight_write(self):
        queue = SnapshotWriteQueue()
        queue.enqueue("k", {"value": 1})
        key, snapshot = queue.take()
        self.assertFalse(queue.wait_empty(0.01))
        queue.finish(key, snapshot, saved=True)
        self.assertTrue(queue.wait_empty(0.05))

    def test_enqueue_copies_snapshot(self):
        queue = SnapshotWriteQueue()
        original = {"nested": {"value": 1}}
        queue.enqueue("k", original)
        original["nested"]["value"] = 99
        key, snapshot = queue.take()
        self.assertEqual(snapshot["nested"]["value"], 1)
        queue.finish(key, snapshot, saved=True)

    def test_failed_write_requeues_when_no_newer_snapshot_exists(self):
        queue = SnapshotWriteQueue()
        queue.enqueue("k", {"version": 1})
        key, snapshot = queue.take()
        queue.finish(key, snapshot, saved=False)
        self.assertEqual(queue.pending_count, 1)
        key2, retry = queue.take()
        self.assertEqual(retry, {"version": 1})
        queue.finish(key2, retry, saved=True)




class FakeJsonbCasStore:
    def __init__(self):
        self.data = {
            "version": 1,
            "products": {"SKU-1": {"quantity": 5}},
            "_write_idempotency": [],
        }
        self.mode = "success"
        self.calls = 0

    def load(self):
        return copy.deepcopy(self.data)

    def patch(self, candidate, expected_version):
        self.calls += 1
        if self.data["version"] != expected_version:
            return False
        if self.mode == "timeout_before" and self.calls == 1:
            raise TimeoutError("request failed before commit")
        if self.mode == "timeout_always":
            raise TimeoutError("persistent network ambiguity before commit")
        self.data = copy.deepcopy(candidate)
        if self.mode == "timeout_after" and self.calls == 1:
            raise TimeoutError("response lost after commit")
        if self.mode == "no_match":
            return False
        return True


def cas_candidate():
    return {
        "version": 2,
        "products": {"SKU-1": {"quantity": 7}},
        "_write_idempotency": [{
            "operation_id": "cas-op-1",
            "request_hash": digest("cas-payload"),
            "version": 2,
            "result": {"ok": True},
        }],
    }


class JsonbCompareAndSwapTests(unittest.TestCase):
    def test_conditional_patch_acknowledges_success(self):
        store = FakeJsonbCasStore()
        cas = JsonbCompareAndSwap(store.load, store.patch)
        self.assertTrue(cas.persist(cas_candidate(), 1, 2))
        self.assertEqual(store.data["version"], 2)

    def test_timeout_after_commit_is_verified_by_idempotency_record(self):
        store = FakeJsonbCasStore()
        store.mode = "timeout_after"
        cas = JsonbCompareAndSwap(store.load, store.patch)
        self.assertTrue(cas.persist(cas_candidate(), 1, 2))
        self.assertEqual(store.data["version"], 2)
        self.assertEqual(store.calls, 1)

    def test_timeout_before_commit_retries_same_candidate(self):
        store = FakeJsonbCasStore()
        store.mode = "timeout_before"
        cas = JsonbCompareAndSwap(store.load, store.patch)
        self.assertTrue(cas.persist(cas_candidate(), 1, 2))
        self.assertEqual(store.calls, 2)
        self.assertEqual(store.data["version"], 2)

    def test_stale_version_is_reported_as_conflict(self):
        store = FakeJsonbCasStore()
        store.data["version"] = 3
        cas = JsonbCompareAndSwap(store.load, store.patch)
        with self.assertRaises(VersionConflict):
            cas.persist(cas_candidate(), 1, 2)

    def test_persistent_timeout_remains_unknown_not_false_success(self):
        store = FakeJsonbCasStore()
        store.mode = "timeout_always"
        cas = JsonbCompareAndSwap(store.load, store.patch)
        with self.assertRaises(CommitOutcomeUnknown):
            cas.persist(cas_candidate(), 1, 2)




if __name__ == "__main__":
    unittest.main()
