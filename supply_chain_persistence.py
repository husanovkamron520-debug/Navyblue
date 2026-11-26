"""Isolated acknowledged-commit adapter prototype for Supply Chain writes.

This module is intentionally NOT wired into bot.py or the Mini App.
The persistence callback must perform an atomic durable compare-and-swap,
including the candidate document's audit and idempotency records.
"""
from __future__ import annotations

import copy
import threading
from typing import Any, Callable


class PersistenceError(RuntimeError):
    """The storage layer did not confirm a durable commit."""


class CommitOutcomeUnknown(PersistenceError):
    """The storage request failed ambiguously; retry with the same operation ID."""


class VersionConflict(PersistenceError):
    """The dataset version changed since the client preview."""


class IdempotencyConflict(PersistenceError):
    """An operation ID was reused with a different request hash."""


class SerializedCommitAdapter:
    """Single-process serialized commit coordinator (prototype only).

    load_snapshot() returns the latest committed document.
    persist_snapshot(candidate, expected_version, new_version) must atomically:
      * compare the stored version with expected_version,
      * persist candidate (including audit/idempotency records),
      * return True only after durable success.

    A process-local lock is NOT sufficient for multiple processes/instances.
    The storage callback must enforce database-side CAS even in single-process
    deployments to protect against other writers and ambiguous retries.
    """

    def __init__(
        self,
        load_snapshot: Callable[[], dict],
        persist_snapshot: Callable[[dict, int, int], bool],
        *,
        max_idempotency_records: int = 1000,
    ) -> None:
        self._load_snapshot = load_snapshot
        self._persist_snapshot = persist_snapshot
        self._max_records = max(1, int(max_idempotency_records))
        self._lock = threading.RLock()

    def commit(
        self,
        *,
        expected_version: int,
        operation_id: str,
        request_hash: str,
        mutate: Callable[[dict], Any],
    ) -> dict:
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 128:
            raise ValueError("operation_id must be a non-empty string of at most 128 characters")
        if not isinstance(request_hash, str) or len(request_hash) != 64:
            raise ValueError("request_hash must be a 64-character SHA-256 hex digest")
        try:
            int(request_hash, 16)
        except ValueError as exc:
            raise ValueError("request_hash must be hexadecimal") from exc
        if isinstance(expected_version, bool) or not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        if not callable(mutate):
            raise TypeError("mutate must be callable")

        # Serializes the complete load -> validate -> mutate -> durable persist path
        # within this process. Database CAS remains mandatory outside this lock.
        with self._lock:
            current = self._load_snapshot()
            if not isinstance(current, dict):
                raise PersistenceError("stored snapshot is not an object")
            current = copy.deepcopy(current)
            current_version = current.get("version", 1)
            if isinstance(current_version, bool) or not isinstance(current_version, int) or current_version < 1:
                raise PersistenceError("stored dataset version is invalid")

            records = current.get("_write_idempotency", [])
            if not isinstance(records, list):
                raise PersistenceError("stored idempotency metadata is invalid")
            for record in reversed(records):
                if not isinstance(record, dict):
                    raise PersistenceError("stored idempotency record is invalid")
                if record.get("operation_id") != operation_id:
                    continue
                stored_hash = record.get("request_hash")
                stored_version = record.get("version")
                if not isinstance(stored_hash, str) or len(stored_hash) != 64:
                    raise PersistenceError("stored idempotency hash is invalid")
                try:
                    int(stored_hash, 16)
                except ValueError as exc:
                    raise PersistenceError("stored idempotency hash is invalid") from exc
                if (isinstance(stored_version, bool) or
                        not isinstance(stored_version, int) or stored_version < 2 or
                        stored_version > current_version):
                    raise PersistenceError("stored idempotency version is invalid")
                if stored_hash != request_hash:
                    raise IdempotencyConflict("operation ID was already used with another payload")
                return {
                    "version": stored_version,
                    "result": copy.deepcopy(record.get("result")),
                    "replayed": True,
                }

            if current_version != expected_version:
                raise VersionConflict(
                    f"expected version {expected_version}, current version {current_version}"
                )

            candidate = copy.deepcopy(current)
            result = mutate(candidate)
            new_version = current_version + 1
            candidate["version"] = new_version

            audit = candidate.get("audit_log", [])
            if not isinstance(audit, list):
                raise PersistenceError("stored audit metadata is invalid")
            audit_entry = {
                "operation_id": operation_id,
                "request_hash": request_hash,
                "previous_version": current_version,
                "new_version": new_version,
            }
            candidate["audit_log"] = (audit + [audit_entry])[-self._max_records:]

            idempotency = list(records)
            idempotency.append({
                "operation_id": operation_id,
                "request_hash": request_hash,
                "version": new_version,
                "result": copy.deepcopy(result),
            })
            candidate["_write_idempotency"] = idempotency[-self._max_records:]

            try:
                acknowledged = self._persist_snapshot(candidate, current_version, new_version)
            except VersionConflict:
                raise
            except Exception as exc:
                # A timeout may happen after the database committed. Never retry
                # with a new ID; reload and retry the exact same operation ID.
                raise CommitOutcomeUnknown(
                    "storage outcome is unknown; retry with the same operation_id"
                ) from exc
            if acknowledged is not True:
                raise PersistenceError("storage did not acknowledge durable commit")

            return {
                "version": new_version,
                "result": copy.deepcopy(result),
                "replayed": False,
            }
