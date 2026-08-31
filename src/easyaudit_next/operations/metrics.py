from __future__ import annotations

from collections import defaultdict
from threading import Lock

from sqlalchemy.engine import Engine


class OperationalMetrics:
    """Small process-local registry with intentionally bounded dimensions."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._http_total: dict[tuple[str, str, str], int] = defaultdict(int)
        self._http_duration_sum: dict[tuple[str, str, str], float] = defaultdict(float)
        self._http_duration_count: dict[tuple[str, str, str], int] = defaultdict(int)
        self._auth_total: dict[str, int] = defaultdict(int)
        self._db_failures: dict[str, int] = defaultdict(int)

    def observe_http(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        key = (method.upper(), route, str(status_code))
        with self._lock:
            self._http_total[key] += 1
            self._http_duration_sum[key] += max(duration_seconds, 0.0)
            self._http_duration_count[key] += 1

    def observe_authentication(self, outcome: str) -> None:
        if outcome not in {"success", "invalid", "throttled"}:
            raise ValueError("Unsupported authentication metric outcome")
        with self._lock:
            self._auth_total[outcome] += 1

    def observe_database_failure(self, failure_class: str) -> None:
        bounded = failure_class if failure_class in {
            "pool_timeout",
            "connect_failure",
            "statement_timeout",
            "lock_timeout",
            "deadlock",
            "other",
        } else "other"
        with self._lock:
            self._db_failures[bounded] += 1

    def render_prometheus(self, engine: Engine | None = None) -> str:
        lines: list[str] = [
            "# TYPE easyaudit_http_requests_total counter",
            "# TYPE easyaudit_http_request_duration_seconds summary",
            "# TYPE easyaudit_authentication_attempts_total counter",
            "# TYPE easyaudit_database_failures_total counter",
        ]
        with self._lock:
            for (method, route, status_code), value in sorted(self._http_total.items()):
                labels = _labels(method=method, route=route, status_code=status_code)
                lines.append(f"easyaudit_http_requests_total{{{labels}}} {value}")
            for key, value in sorted(self._http_duration_sum.items()):
                method, route, status_code = key
                labels = _labels(method=method, route=route, status_code=status_code)
                lines.append(
                    f"easyaudit_http_request_duration_seconds_sum{{{labels}}} {value:.9f}"
                )
                lines.append(
                    "easyaudit_http_request_duration_seconds_count"
                    f"{{{labels}}} {self._http_duration_count[key]}"
                )
            for outcome, value in sorted(self._auth_total.items()):
                lines.append(
                    "easyaudit_authentication_attempts_total"
                    f'{{outcome="{outcome}"}} {value}'
                )
            for failure_class, value in sorted(self._db_failures.items()):
                lines.append(
                    "easyaudit_database_failures_total"
                    f'{{failure_class="{failure_class}"}} {value}'
                )

        if engine is not None:
            pool = engine.pool
            size = getattr(pool, "size", lambda: 0)()
            checked_out = getattr(pool, "checkedout", lambda: 0)()
            overflow = getattr(pool, "overflow", lambda: 0)()
            lines.extend(
                [
                    "# TYPE easyaudit_database_pool_size gauge",
                    f"easyaudit_database_pool_size {size}",
                    "# TYPE easyaudit_database_pool_checked_out gauge",
                    f"easyaudit_database_pool_checked_out {checked_out}",
                    "# TYPE easyaudit_database_pool_overflow gauge",
                    f"easyaudit_database_pool_overflow {overflow}",
                ]
            )
        return "\n".join(lines) + "\n"


def _labels(**values: str) -> str:
    return ",".join(f'{name}="{_escape(value)}"' for name, value in values.items())


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


metrics = OperationalMetrics()
