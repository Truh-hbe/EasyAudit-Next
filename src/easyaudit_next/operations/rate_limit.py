from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import blake2b
from math import ceil
from secrets import token_bytes
from threading import Lock
from time import monotonic
from typing import Callable

from easyaudit_next.platform.login_identity import normalize_login_name


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    allowed: bool
    retry_after_seconds: int = 0


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float
    last_used_at: float


class LoginRateLimiter:
    """Atomic process-local global + normalized-login/source token buckets."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        global_capacity: float = 20.0,
        global_refill_per_second: float = 1.0,
        per_key_capacity: float = 5.0,
        per_key_refill_per_second: float = 1.0 / 12.0,
        max_entries: int = 4096,
        entry_ttl_seconds: float = 3600.0,
        fingerprint_key: bytes | None = None,
    ) -> None:
        if min(
            global_capacity,
            global_refill_per_second,
            per_key_capacity,
            per_key_refill_per_second,
            max_entries,
            entry_ttl_seconds,
        ) <= 0:
            raise ValueError("Rate limiter budgets must be positive")
        self._clock = clock
        now = clock()
        self._global = _Bucket(global_capacity, now, now)
        self._global_capacity = global_capacity
        self._global_refill = global_refill_per_second
        self._per_capacity = per_key_capacity
        self._per_refill = per_key_refill_per_second
        self._max_entries = max_entries
        self._entry_ttl = entry_ttl_seconds
        self._key = fingerprint_key or token_bytes(32)
        self._entries: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = Lock()

    def admit(self, login_name: str, source_identity: str) -> AdmissionDecision:
        normalized_login = normalize_login_name(login_name)
        fingerprint = self._fingerprint(normalized_login, source_identity)
        now = self._clock()
        with self._lock:
            self._evict(now)
            global_bucket = self._refilled(
                self._global,
                now,
                self._global_capacity,
                self._global_refill,
            )
            existing = self._entries.get(fingerprint)
            per_bucket = self._refilled(
                existing or _Bucket(self._per_capacity, now, now),
                now,
                self._per_capacity,
                self._per_refill,
            )

            global_allows = global_bucket.tokens >= 1.0
            per_allows = per_bucket.tokens >= 1.0
            if global_allows and per_allows:
                global_bucket.tokens -= 1.0
                per_bucket.tokens -= 1.0
                per_bucket.last_used_at = now
                self._global = global_bucket
                self._entries[fingerprint] = per_bucket
                self._entries.move_to_end(fingerprint)
                self._trim()
                return AdmissionDecision(True)

            # Refill bookkeeping is not token consumption. Never decrement either
            # bucket unless both have capacity for the same operation.
            self._global = global_bucket
            if existing is not None:
                per_bucket.last_used_at = now
                self._entries[fingerprint] = per_bucket
                self._entries.move_to_end(fingerprint)
            retry = max(
                self._retry_after(global_bucket.tokens, self._global_refill),
                self._retry_after(per_bucket.tokens, self._per_refill),
            )
            return AdmissionDecision(False, retry_after_seconds=max(1, retry))

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def global_tokens(self) -> float:
        with self._lock:
            return self._global.tokens

    def _fingerprint(self, normalized_login: str, source_identity: str) -> str:
        digest = blake2b(key=self._key, digest_size=16)
        digest.update(normalized_login.encode("utf-8", errors="ignore"))
        digest.update(b"\x00")
        digest.update(source_identity.encode("utf-8", errors="ignore"))
        return digest.hexdigest()

    @staticmethod
    def _refilled(
        bucket: _Bucket,
        now: float,
        capacity: float,
        refill_per_second: float,
    ) -> _Bucket:
        elapsed = max(0.0, now - bucket.updated_at)
        return _Bucket(
            tokens=min(capacity, bucket.tokens + elapsed * refill_per_second),
            updated_at=now,
            last_used_at=bucket.last_used_at,
        )

    @staticmethod
    def _retry_after(tokens: float, refill_per_second: float) -> int:
        if tokens >= 1.0:
            return 0
        return ceil((1.0 - tokens) / refill_per_second)

    def _evict(self, now: float) -> None:
        expired = [
            key
            for key, bucket in self._entries.items()
            if now - bucket.last_used_at > self._entry_ttl
        ]
        for key in expired:
            self._entries.pop(key, None)

    def _trim(self) -> None:
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
