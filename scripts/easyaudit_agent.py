#!/usr/bin/env python3
"""OMP Agent control-plane helper for EasyAudit-Next.

The helper is deliberately standard-library only. It owns local state inspection,
writer leases, typed state transitions, bounded command profiles and independent
GitHub evidence checks. Product/domain code must never import this module.
"""

from __future__ import annotations

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import uuid4

ROOT = Path(os.getenv("EASYAUDIT_REPO_ROOT", Path(__file__).resolve().parents[1])).resolve()
STATE_PATH = ROOT / ".easyaudit" / "development-state.json"
POLICY_PATH = ROOT / ".easyaudit" / "workflow-policy.json"
RUNTIME_DIR = ROOT / ".easyaudit" / "runtime"
LEASE_PATH = RUNTIME_DIR / "omp-agent-lease.json"
LEASE_GUARD_PATH = RUNTIME_DIR / "omp-agent-lease.guard"
EXPECTED_POLICY_HASH = "31e7c9d4aa8b9f61c20b1d95b85f948ceb919d1d91938c80c5b2006748780857"
LEASE_TTL_SECONDS = 30.0
DOCS_ONLY_STATE_PATH = ".easyaudit/development-state.json"
WORKFLOW_POLICY_PATH = ".easyaudit/workflow-policy.json"
PROTECTED_PATHS = {DOCS_ONLY_STATE_PATH, WORKFLOW_POLICY_PATH}
SENSITIVE_READ_PATTERNS = {
    ".env",
    ".env.*",
    ".git/**",
    ".easyaudit/runtime/**",
}
READ_ONLY_TOOLS = {
    "read",
    "grep",
    "find",
    "ls",
    "ea_status",
    "ea_preflight",
    "ea_verify",
    "ea_next",
}
MUTATING_TOOLS = {"edit", "write", "ast_edit", "bash", "powershell"}
FORWARD_PHASES = {
    "GATE_DRAFT": {"GATE_REVIEW"},
    "GATE_REVIEW": {"IMPLEMENTATION", "MERGE_AUTHORIZED"},
    "IMPLEMENTATION": {"FINAL_REVIEW"},
    "FINAL_REVIEW": {"MERGE_AUTHORIZED"},
    "MERGE_AUTHORIZED": {"MERGED"},
    "MERGED": set(),
}
ROLLBACK_PHASES = {
    ("GATE_REVIEW", "GATE_DRAFT"),
    ("FINAL_REVIEW", "IMPLEMENTATION"),
    ("MERGE_AUTHORIZED", "FINAL_REVIEW"),
}
COMMAND_PROFILES: dict[str, tuple[str, ...]] = {
    "git-status": ("git", "status", "--short"),
    "git-diff": ("git", "diff", "--stat"),
    "git-log": ("git", "log", "-n", "8", "--oneline", "--decorate"),
    "git-fetch": ("git", "fetch", "origin"),
    "gate-check": (sys.executable, "scripts/easyaudit_gate.py", "check"),
    "gate-bundle": (sys.executable, "scripts/easyaudit_gate.py", "bundle"),
    "tooling-tests": (sys.executable, "-m", "pytest", "tests/tooling"),
    "architecture-check": (sys.executable, "scripts/check_architecture.py"),
    "openapi-check": (sys.executable, "scripts/check_openapi.py"),
}
MUTATING_PROFILES = {
    "git-fetch",
    "gate-bundle",
    "git-commit",
    "git-push",
    "git-push-main-rebaseline",
}


class ControlError(RuntimeError):
    """A bounded control-plane refusal."""


@dataclass(frozen=True, slots=True)
class Owner:
    session_id: str
    session_file: str | None
    pid: int
    hostname: str


@dataclass(frozen=True, slots=True)
class LeaseResult:
    allowed: bool
    reason: str
    lease: dict[str, Any] | None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _redact_output(value: str) -> str:
    redacted = value
    sensitive_names = ("SECRET", "TOKEN", "PASSWORD", "COOKIE", "KEY", "DATABASE")
    for name, secret in os.environ.items():
        upper = name.upper()
        if secret and any(token in upper for token in sensitive_names):
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(?i)(cookie:\s*)[^\r\n]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[REDACTED]@", redacted)
    return redacted


def _json_output(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _fail(message: str, *, code: int = 2) -> NoReturn:
    _json_output({"pass": False, "reason": message})
    raise SystemExit(code)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ControlError(f"required file is missing: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise ControlError(f"invalid JSON: {path.relative_to(ROOT)}") from exc
    if not isinstance(value, dict):
        raise ControlError(f"JSON root must be an object: {path.relative_to(ROOT)}")
    return value


def load_state() -> dict[str, Any]:
    state = _load_json(STATE_PATH)
    if state.get("schema_version") != 1:
        raise ControlError("unsupported development-state schema")
    return state


def canonical_policy_hash(policy: dict[str, Any] | None = None) -> str:
    resolved = policy if policy is not None else _load_json(POLICY_PATH)
    canonical = json.dumps(
        resolved,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_trusted_policy() -> dict[str, Any]:
    policy = _load_json(POLICY_PATH)
    if canonical_policy_hash(policy) != EXPECTED_POLICY_HASH:
        raise ControlError("workflow policy canonical hash is not trusted")
    if policy.get("policy_change_protocol") != "separate-reviewed-policy-seed":
        raise ControlError("workflow policy change protocol is not trusted")
    return policy


def _git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise ControlError(f"git command failed: {' '.join(args[:2])}")
    return completed.stdout.strip()


def _run(argv: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(argv),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise ControlError(f"approved command failed: {Path(argv[0]).name}")
    return completed


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def current_owner() -> Owner:
    return Owner(
        session_id=(
            os.getenv("PI_SESSION_ID")
            or os.getenv("OMP_SESSION_ID")
            or f"pid-{os.getpid()}"
        ),
        session_file=os.getenv("PI_SESSION_FILE") or os.getenv("OMP_SESSION_FILE"),
        pid=os.getpid(),
        hostname=socket.gethostname(),
    )


def _owner_matches(lease: dict[str, Any], owner: Owner) -> bool:
    return (
        lease.get("session_id") == owner.session_id
        and lease.get("pid") == owner.pid
        and lease.get("hostname") == owner.hostname
    )


def _process_alive(lease: dict[str, Any]) -> bool | None:
    if lease.get("hostname") != socket.gethostname():
        return None
    pid = lease.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _heartbeat_age(lease: dict[str, Any], now: float) -> float:
    value = lease.get("heartbeat_epoch")
    return now - float(value) if isinstance(value, (int, float)) else float("inf")


@contextmanager
def _lease_guard() -> Iterator[None]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with LEASE_GUARD_PATH.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_lease() -> dict[str, Any] | None:
    try:
        value = json.loads(LEASE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ControlError("writer lease JSON is invalid") from exc
    if not isinstance(value, dict):
        raise ControlError("writer lease root is invalid")
    return value


def _write_lease(lease: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="lease-", suffix=".json", dir=RUNTIME_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(lease, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, LEASE_PATH)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def acquire_lease(*, takeover: bool = False, expected_generation: str | None = None) -> LeaseResult:
    owner = current_owner()
    now = time.time()
    with _lease_guard():
        existing = _read_lease()
        if existing is not None and _owner_matches(existing, owner):
            existing["heartbeat_at"] = _utc_now()
            existing["heartbeat_epoch"] = now
            _write_lease(existing)
            return LeaseResult(True, "writer lease already owned", existing)

        if existing is not None:
            alive = _process_alive(existing)
            stale = _heartbeat_age(existing, now) > LEASE_TTL_SECONDS
            generation_matches = expected_generation == existing.get("generation_nonce")
            if not takeover:
                return LeaseResult(False, "another OMP Session owns the writer lease", existing)
            if not stale or alive is not False or not generation_matches:
                return LeaseResult(
                    False,
                    "writer lease takeover preconditions are not satisfied",
                    existing,
                )

        generation = uuid4().hex
        lease = {
            "schema_version": 1,
            "repository_realpath": str(ROOT.resolve()),
            "session_id": owner.session_id,
            "session_file": owner.session_file,
            "pid": owner.pid,
            "hostname": owner.hostname,
            "branch": _git("branch", "--show-current"),
            "generation_nonce": generation,
            "acquired_at": _utc_now(),
            "heartbeat_at": _utc_now(),
            "heartbeat_epoch": now,
            "mode": "writer",
        }
        _write_lease(lease)
        return LeaseResult(True, "writer lease acquired", lease)


def heartbeat_lease(generation: str) -> LeaseResult:
    owner = current_owner()
    with _lease_guard():
        lease = _read_lease()
        if lease is None or not _owner_matches(lease, owner):
            return LeaseResult(False, "writer lease is not owned by this Session", lease)
        if lease.get("generation_nonce") != generation:
            return LeaseResult(False, "writer lease generation mismatch", lease)
        lease["heartbeat_at"] = _utc_now()
        lease["heartbeat_epoch"] = time.time()
        _write_lease(lease)
        return LeaseResult(True, "writer lease heartbeat updated", lease)


def release_lease(generation: str) -> LeaseResult:
    owner = current_owner()
    with _lease_guard():
        lease = _read_lease()
        if lease is None:
            return LeaseResult(True, "writer lease is already absent", None)
        if not _owner_matches(lease, owner) or lease.get("generation_nonce") != generation:
            return LeaseResult(
                False,
                "only the current owner generation may release the lease",
                lease,
            )
        LEASE_PATH.unlink(missing_ok=True)
        return LeaseResult(True, "writer lease released", None)


def lease_status() -> LeaseResult:
    with _lease_guard():
        lease = _read_lease()
    if lease is None:
        return LeaseResult(False, "no writer lease", None)
    return LeaseResult(_owner_matches(lease, current_owner()), "writer lease present", lease)


def _normalized_repo_path(path: str) -> tuple[str, Path]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ControlError("path is outside the repository") from exc
    return relative, resolved


def _matches(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def runtime_write_capable(mode: str) -> bool:
    if mode == "tui":
        return True
    if mode == "rpc":
        return os.getenv("EASYAUDIT_OMP_RPC_BASH_GUARDED") == "1"
    return False


def guard_tool(tool_name: str, *, path: str | None, mode: str) -> tuple[bool, str]:
    state = load_state()
    if tool_name in READ_ONLY_TOOLS:
        if path is not None and tool_name in {"read", "grep", "find", "ls"}:
            relative, _ = _normalized_repo_path(path)
            if _matches(relative, list(SENSITIVE_READ_PATTERNS)):
                return False, "read target is inside a protected runtime or secret path"
        return True, "dedicated read-only tool"

    if not runtime_write_capable(mode):
        return False, "runtime mode is read-only-no-go"

    lease = lease_status()
    if not lease.allowed:
        return False, "no writer lease; all model bash and mutating tools are blocked"

    if tool_name in {"bash", "powershell"}:
        return False, "arbitrary model shell is disabled; use ea_exec command profiles"

    if tool_name in {"edit", "write", "ast_edit"}:
        if path is None:
            return False, "mutating file tool did not provide a target path"
        relative, _ = _normalized_repo_path(path)
        if relative in PROTECTED_PATHS:
            return False, "policy roots require a typed control-plane adapter"
        if not state.get("active"):
            return False, "inactive state requires an explicit new-slice bootstrap"
        scope = state.get("scope") or {}
        allowed = [str(value) for value in scope.get("allowed_paths") or []]
        forbidden = [str(value) for value in scope.get("forbidden_paths") or []]
        if _matches(relative, forbidden):
            return False, "target path is forbidden by the active Gate"
        if not _matches(relative, allowed):
            return False, "target path is outside the active Gate allowlist"
        if state.get("phase") in {"FINAL_REVIEW", "MERGE_AUTHORIZED"}:
            finalization = [str(value) for value in state.get("finalization_allowed_paths") or []]
            if not _matches(relative, finalization):
                return False, "candidate is frozen; only finalization paths may change"
        return True, "writer lease and Gate scope permit this path"

    if tool_name.startswith("ea_"):
        return True, "registered EasyAudit control-plane tool"
    if tool_name in MUTATING_TOOLS or tool_name not in READ_ONLY_TOOLS:
        return False, "unknown or mutating tool is denied by default"
    return True, "read-only tool"


def _trusted_main_ref() -> str:
    for candidate in ("refs/remotes/origin/main", "refs/heads/main"):
        if subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", candidate],
            cwd=ROOT,
            check=False,
        ).returncode == 0:
            return candidate
    raise ControlError("trusted main ref is unavailable")


def _completion_commit(slice_name: str, trusted_main: str) -> str | None:
    commits = _git("log", "--format=%H", trusted_main, "--", str(STATE_PATH.relative_to(ROOT)))
    for commit in commits.splitlines():
        completed = subprocess.run(
            ["git", "show", f"{commit}:{STATE_PATH.relative_to(ROOT).as_posix()}"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode != 0:
            continue
        try:
            state = json.loads(completed.stdout)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(state, dict)
            and state.get("slice") == slice_name
            and state.get("phase") == "MERGED"
            and state.get("active") is False
        ):
            return commit
    return None


def verify_predecessors(state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    resolved_state = state or load_state()
    policy = load_trusted_policy()
    slice_name = str(resolved_state.get("slice", ""))
    configured = policy.get("slice_predecessors") or {}
    predecessors = configured.get(slice_name, []) if isinstance(configured, dict) else []
    if not isinstance(predecessors, list):
        raise ControlError("workflow predecessor contract is invalid")
    base = str((resolved_state.get("base") or {}).get("sha") or "")
    head = _git("rev-parse", "HEAD")
    trusted_main = _trusted_main_ref()
    results: list[dict[str, Any]] = []
    for predecessor in predecessors:
        if not isinstance(predecessor, str):
            raise ControlError("workflow predecessor name is invalid")
        completion = _completion_commit(predecessor, trusted_main)
        passed = bool(
            completion
            and base
            and _is_ancestor(completion, base)
            and _is_ancestor(completion, head)
        )
        results.append(
            {
                "slice": predecessor,
                "completion_commit": completion,
                "base_ancestor": bool(completion and base and _is_ancestor(completion, base)),
                "head_ancestor": bool(completion and _is_ancestor(completion, head)),
                "pass": passed,
            }
        )
    return results


def _gate_check(*extra: str) -> bool:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("easyaudit_gate.py")), "check", *extra],
        cwd=ROOT,
        env={**os.environ, "EASYAUDIT_REPO_ROOT": str(ROOT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def status_payload(*, mode: str) -> dict[str, Any]:
    state = load_state()
    policy_hash: str | None
    try:
        policy_hash = canonical_policy_hash()
    except ControlError:
        policy_hash = None
    lease = lease_status()
    predecessors: list[dict[str, Any]] | None
    try:
        predecessors = verify_predecessors(state)
    except ControlError:
        predecessors = None
    return {
        "project": state.get("project"),
        "slice": state.get("slice"),
        "phase": state.get("phase"),
        "active": state.get("active"),
        "branch": _git("branch", "--show-current"),
        "head": _git("rev-parse", "HEAD"),
        "base": (state.get("base") or {}).get("sha"),
        "candidate": state.get("fixed_head") or state.get("docs_review_head"),
        "working_tree_clean": _git("status", "--porcelain=v1") == "",
        "gate_pass": _gate_check(),
        "writer_lease_owned": lease.allowed,
        "writer_lease": _public_lease(lease.lease),
        "runtime_mode": mode,
        "runtime_write_capable": runtime_write_capable(mode),
        "protection_mode": "protected-write"
        if runtime_write_capable(mode) and lease.allowed
        else "read-only-no-go",
        "policy_hash": policy_hash,
        "policy_trusted": policy_hash == EXPECTED_POLICY_HASH,
        "predecessors": predecessors,
        "next_allowed_action": state.get("next_allowed_action"),
        "remote_evidence": "not-fetched",
    }


def _public_lease(lease: dict[str, Any] | None) -> dict[str, Any] | None:
    if lease is None:
        return None
    return {
        key: lease.get(key)
        for key in (
            "session_id",
            "pid",
            "hostname",
            "branch",
            "generation_nonce",
            "heartbeat_at",
            "mode",
        )
    }


def _remote_required_contexts(base_branch: str) -> tuple[set[str] | None, str]:
    repository = _run(
        ("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"),
        check=False,
    )
    if repository.returncode != 0 or not repository.stdout.strip():
        return None, "unavailable"
    slug = repository.stdout.strip()
    protection = _run(
        (
            "gh",
            "api",
            f"repos/{slug}/branches/{base_branch}/protection/required_status_checks",
        ),
        check=False,
    )
    if protection.returncode == 0:
        try:
            payload = json.loads(protection.stdout)
            contexts = set(payload.get("contexts") or [])
            contexts.update(
                item.get("context")
                for item in payload.get("checks") or []
                if isinstance(item, dict) and isinstance(item.get("context"), str)
            )
            return {str(value) for value in contexts if value}, "github-branch-protection"
        except json.JSONDecodeError:
            return None, "unavailable"

    rulesets = _run(
        ("gh", "api", f"repos/{slug}/rulesets?includes_parents=true"),
        check=False,
    )
    if rulesets.returncode == 0:
        try:
            payload = json.loads(rulesets.stdout)
        except json.JSONDecodeError:
            return None, "unavailable"
        contexts: set[str] = set()
        if isinstance(payload, list):
            for ruleset in payload:
                if not isinstance(ruleset, dict) or ruleset.get("enforcement") == "disabled":
                    continue
                for rule in ruleset.get("rules") or []:
                    if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
                        continue
                    parameters = rule.get("parameters") or {}
                    for item in parameters.get("required_status_checks") or []:
                        if isinstance(item, dict) and isinstance(item.get("context"), str):
                            contexts.add(item["context"])
        return contexts, "github-rulesets"
    return None, "unavailable"


def verify_pr(pr_number: int) -> dict[str, Any]:
    policy = load_trusted_policy()
    required = policy.get("required_checks") or {}
    main = required.get("main") if isinstance(required, dict) else None
    contexts = main.get("contexts") if isinstance(main, dict) else None
    if not isinstance(contexts, list) or not contexts or not all(
        isinstance(item, str) for item in contexts
    ):
        raise ControlError("authoritative required-check contract is unavailable")

    view = _run(
        (
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "state,isDraft,mergeable,headRefName,baseRefName,headRefOid,baseRefOid,mergedAt,url",
        )
    )
    pr = json.loads(view.stdout)
    contract_contexts = {str(item) for item in contexts}
    remote_contexts, remote_source = _remote_required_contexts(str(pr.get("baseRefName") or "main"))
    if remote_contexts is not None and remote_contexts != contract_contexts:
        raise ControlError("GitHub required checks drift from the trusted policy contract")
    required_source = (
        remote_source if remote_contexts is not None else "trusted-base-versioned-contract"
    )
    checks_result = _run(
        ("gh", "pr", "checks", str(pr_number), "--json", "name,state,bucket,link"),
        check=False,
    )
    if checks_result.returncode not in (0, 8):
        raise ControlError("GitHub required-check evidence is unavailable")
    checks = json.loads(checks_result.stdout or "[]")
    by_name = {item.get("name"): item for item in checks if isinstance(item, dict)}
    evidence = []
    for context in contexts:
        item = by_name.get(context)
        passed = bool(item and item.get("bucket") == "pass")
        evidence.append(
            {
                "name": context,
                "pass": passed,
                "state": item.get("state") if item else None,
            }
        )
    return {
        "fetched_at": _utc_now(),
        "pr": pr,
        "required_source": required_source,
        "required_checks": evidence,
        "pass": all(item["pass"] for item in evidence),
    }


def _validate_scope_immutability(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    post_merge: bool = False,
) -> None:
    immutable = ["project", "slice", "pr", "candidate_kind", "gate_docs"]
    if not post_merge:
        immutable.extend(("base", "work_branch"))
    for key in immutable:
        if old.get(key) != new.get(key):
            raise ControlError(f"ordinary transition cannot change {key}")
    old_scope = old.get("scope") or {}
    new_scope = new.get("scope") or {}
    old_allowed = set(old_scope.get("allowed_paths") or [])
    new_allowed = set(new_scope.get("allowed_paths") or [])
    old_forbidden = set(old_scope.get("forbidden_paths") or [])
    new_forbidden = set(new_scope.get("forbidden_paths") or [])
    if not new_allowed.issubset(old_allowed):
        raise ControlError("ordinary transition cannot widen allowed_paths")
    if not new_forbidden.issuperset(old_forbidden):
        raise ControlError("ordinary transition cannot weaken forbidden_paths")
    if not set(new.get("finalization_allowed_paths") or []).issubset(
        set(old.get("finalization_allowed_paths") or [])
    ):
        raise ControlError("ordinary transition cannot widen finalization paths")


def validate_state_transition(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    rollback_reason: str | None = None,
) -> None:
    old_phase = str(old.get("phase"))
    new_phase = str(new.get("phase"))
    is_forward = new_phase in FORWARD_PHASES.get(old_phase, set())
    is_rollback = (old_phase, new_phase) in ROLLBACK_PHASES
    if not is_forward and not is_rollback:
        raise ControlError(f"illegal phase transition: {old_phase} -> {new_phase}")
    _validate_scope_immutability(old, new, post_merge=new_phase == "MERGED")
    if is_rollback and not rollback_reason:
        raise ControlError("rollback transition requires a bounded reason")
    if new_phase in {"GATE_DRAFT", "IMPLEMENTATION"} and is_rollback:
        if new.get("fixed_head") not in (None, "") or new.get("docs_review_head") not in (None, ""):
            raise ControlError("rollback must clear invalid candidate references")
    candidate_kind = new.get("candidate_kind", "executable")
    if new_phase == "GATE_REVIEW":
        candidate = new.get("docs_review_head")
        if candidate_kind != "docs-only" or not isinstance(candidate, str):
            raise ControlError("GATE_REVIEW requires a docs-only reviewed head")
        if not _is_ancestor(candidate, _git("rev-parse", "HEAD")):
            raise ControlError("docs review head is not an ancestor")
    if new_phase in {"FINAL_REVIEW", "MERGE_AUTHORIZED"} and candidate_kind == "executable":
        candidate = new.get("fixed_head")
        if not isinstance(candidate, str) or not _is_ancestor(candidate, _git("rev-parse", "HEAD")):
            raise ControlError("fixed candidate is missing or not an ancestor")


def _atomic_write_state(old_bytes: bytes, proposed: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".json", dir=STATE_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(proposed, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, STATE_PATH)
        if not _gate_check():
            STATE_PATH.write_bytes(old_bytes)
            raise ControlError("proposed state failed the repository Gate")
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def bootstrap_state(
    *,
    kind: str,
    slice_name: str,
    milestone: str,
    branch: str,
    base_sha: str,
    gate_docs: Sequence[str],
    allowed_paths: Sequence[str],
    forbidden_paths: Sequence[str],
    include_roadmap: bool,
) -> dict[str, Any]:
    old_bytes = STATE_PATH.read_bytes()
    old = load_state()
    if old.get("active") is not False or old.get("phase") != "MERGED":
        raise ControlError("new Slice bootstrap requires an inactive MERGED state")
    if _git("rev-parse", "HEAD") != base_sha:
        raise ControlError("bootstrap base must equal current HEAD")
    if _git("branch", "--show-current") != branch:
        raise ControlError("bootstrap branch must equal the current branch")
    load_trusted_policy()
    normalized_gate_docs: list[str] = []
    created_gate_docs: list[Path] = []
    for path in gate_docs:
        relative, resolved = _normalized_repo_path(path)
        if not relative.startswith("docs/architecture/") or not relative.endswith(".md"):
            raise ControlError("Gate documents must be Markdown under docs/architecture")
        normalized_gate_docs.append(relative)
        if kind == "gate" and not resolved.exists():
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text("# Gate Draft\n", encoding="utf-8")
            created_gate_docs.append(resolved)
        if kind == "implementation" and not resolved.is_file():
            raise ControlError("implementation bootstrap requires merged Gate documents")

    if kind == "gate":
        allowed = [DOCS_ONLY_STATE_PATH, *normalized_gate_docs]
        if include_roadmap:
            allowed.append("docs/architecture/roadmap.md")
        candidate_kind = "docs-only"
        phase = "GATE_DRAFT"
    elif kind == "implementation":
        allowed = list(dict.fromkeys(allowed_paths))
        if DOCS_ONLY_STATE_PATH not in allowed:
            allowed.insert(0, DOCS_ONLY_STATE_PATH)
        if WORKFLOW_POLICY_PATH in allowed or any(
            _matches(WORKFLOW_POLICY_PATH, [pattern]) for pattern in allowed
        ):
            raise ControlError("implementation bootstrap must not allow workflow policy")
        candidate_kind = "executable"
        phase = "IMPLEMENTATION"
    else:
        raise ControlError("unsupported bootstrap kind")

    forbidden = list(dict.fromkeys(forbidden_paths))
    if WORKFLOW_POLICY_PATH not in forbidden:
        forbidden.insert(0, WORKFLOW_POLICY_PATH)
    proposed = {
        "schema_version": 1,
        "active": True,
        "project": "EasyAudit-Next",
        "milestone": milestone,
        "slice": slice_name,
        "phase": phase,
        "base": {"branch": "main", "sha": base_sha},
        "work_branch": branch,
        "pr": {"number": None},
        "gate_docs": normalized_gate_docs,
        "candidate_kind": candidate_kind,
        "scope": {"allowed_paths": allowed, "forbidden_paths": forbidden},
        "fixed_head": None,
        "docs_review_head": None,
        "finalization_allowed_paths": [DOCS_ONLY_STATE_PATH],
        "next_allowed_action": (
            "Draft and review this Gate only"
            if kind == "gate"
            else "Implement this reviewed Slice only"
        ),
    }
    predecessor_results = verify_predecessors(proposed)
    if any(not result["pass"] for result in predecessor_results):
        raise ControlError("bootstrap predecessor completion is missing from base ancestry")
    try:
        _atomic_write_state(old_bytes, proposed)
    except Exception:
        if kind == "gate":
            for candidate in created_gate_docs:
                candidate.unlink(missing_ok=True)
        raise
    return proposed


def record_pr_number(pr_number: int) -> dict[str, Any]:
    if pr_number <= 0:
        raise ControlError("PR number must be positive")
    old_bytes = STATE_PATH.read_bytes()
    state = load_state()
    if state.get("phase") not in {"GATE_DRAFT", "IMPLEMENTATION"}:
        raise ControlError("PR may only be recorded in a draft/implementation phase")
    current = (state.get("pr") or {}).get("number")
    if current not in (None, pr_number):
        raise ControlError("PR number is already bound to another PR")
    proposed = json.loads(json.dumps(state))
    proposed["pr"] = {"number": pr_number}
    _atomic_write_state(old_bytes, proposed)
    return proposed


def sync_pr_metadata(state: dict[str, Any]) -> str:
    pr_number = (state.get("pr") or {}).get("number")
    if not isinstance(pr_number, int):
        return "not-applicable"
    start = "<!-- easyaudit-status:start -->"
    end = "<!-- easyaudit-status:end -->"
    head = _git("rev-parse", "HEAD")
    block = "\n".join(
        (
            start,
            "```text",
            f"phase={state.get('phase')}",
            f"candidate={state.get('fixed_head') or state.get('docs_review_head') or 'none'}",
            f"control_head={head}",
            "```",
            end,
        )
    )
    try:
        viewed = _run(("gh", "pr", "view", str(pr_number), "--json", "body"))
        payload = json.loads(viewed.stdout)
        body = str(payload.get("body") or "")
        if start in body and end in body:
            prefix = body.split(start, 1)[0].rstrip()
            suffix = body.split(end, 1)[1].lstrip()
            body = "\n\n".join(value for value in (prefix, block, suffix) if value)
        else:
            body = f"{body.rstrip()}\n\n{block}\n".lstrip()
        updated = _run(
            ("gh", "pr", "edit", str(pr_number), "--body", body),
            check=False,
        )
        if updated.returncode != 0:
            return "drift"
        confirmed = _run(("gh", "pr", "view", str(pr_number), "--json", "body"))
        confirmed_body = str(json.loads(confirmed.stdout).get("body") or "")
        return "current" if block in confirmed_body else "drift"
    except (ControlError, json.JSONDecodeError):
        return "drift"


def transition_state(
    target: str,
    *,
    candidate: str | None,
    rollback_reason: str | None,
    review_pass_ref: str | None,
) -> dict[str, Any]:
    old_bytes = STATE_PATH.read_bytes()
    old = load_state()
    new = json.loads(json.dumps(old))
    new["phase"] = target
    if target == "GATE_REVIEW":
        new["docs_review_head"] = candidate
    elif target == "FINAL_REVIEW":
        if _git("status", "--porcelain=v1"):
            raise ControlError("FINAL_REVIEW requires a clean working tree")
        if not _gate_check("--require-clean", "--require-bundle"):
            raise ControlError("FINAL_REVIEW requires a current clean Review Bundle")
        new["fixed_head"] = candidate
    elif target == "MERGE_AUTHORIZED":
        if not review_pass_ref:
            raise ControlError("MERGE_AUTHORIZED requires an independent Review PASS reference")
        pr_number = (old.get("pr") or {}).get("number")
        if not isinstance(pr_number, int):
            raise ControlError("MERGE_AUTHORIZED requires a PR number")
        evidence = verify_pr(pr_number)
        if not evidence["pass"]:
            raise ControlError("required exact-head CI is not green")
    elif target == "MERGED":
        if _git("branch", "--show-current") != "main":
            raise ControlError("post-merge rebaseline must run on main")
        pr_number = (old.get("pr") or {}).get("number")
        if not isinstance(pr_number, int):
            raise ControlError("post-merge rebaseline requires a PR number")
        evidence = verify_pr(pr_number)
        if evidence["pr"].get("state") != "MERGED":
            raise ControlError("GitHub does not report the PR as merged")
        new["active"] = False
        new["base"] = {"branch": "main", "sha": _git("rev-parse", "HEAD")}
        new["work_branch"] = None
        new["next_allowed_action"] = (
            "Await explicit authorization for the next policy-approved Slice"
        )
    elif target in {"GATE_DRAFT", "IMPLEMENTATION"}:
        new["fixed_head"] = None
        new["docs_review_head"] = None
    validate_state_transition(old, new, rollback_reason=rollback_reason)
    _atomic_write_state(old_bytes, new)
    return new


def execute_profile(profile: str, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if any(value in {";", "|", ">", ">>", "<", "&&", "||"} for value in arguments):
        raise ControlError("shell control tokens are forbidden in command profiles")
    if profile in COMMAND_PROFILES:
        if arguments:
            raise ControlError("this command profile accepts no arguments")
        return _run(COMMAND_PROFILES[profile], check=False)
    if profile == "git-commit":
        if len(arguments) != 1 or not arguments[0].strip():
            raise ControlError("git-commit requires one commit message")
        state = load_state()
        changed = _git("status", "--porcelain=v1")
        paths = [line[3:] for line in changed.splitlines() if len(line) > 3]
        scope = state.get("scope") or {}
        allowed = [str(value) for value in scope.get("allowed_paths") or []]
        forbidden = [str(value) for value in scope.get("forbidden_paths") or []]
        for path in paths:
            if (
                path == WORKFLOW_POLICY_PATH
                or _matches(path, forbidden)
                or not _matches(path, allowed)
            ):
                raise ControlError("git-commit found a protected or out-of-scope path")
        _run(("git", "add", "--", *paths))
        completed = _run(("git", "commit", "-m", arguments[0]), check=False)
        if completed.returncode == 0:
            sync_pr_metadata(load_state())
        return completed
    if profile == "git-push":
        if arguments:
            raise ControlError("git-push accepts no arguments")
        branch = _git("branch", "--show-current")
        if not branch or branch == "main":
            raise ControlError("profile refuses direct push to main")
        return _run(("git", "push", "origin", branch), check=False)
    if profile == "git-push-main-rebaseline":
        if arguments:
            raise ControlError("git-push-main-rebaseline accepts no arguments")
        state = load_state()
        if (
            _git("branch", "--show-current") != "main"
            or state.get("active") is not False
            or state.get("phase") != "MERGED"
        ):
            raise ControlError("main push is limited to a completed post-merge rebaseline")
        return _run(("git", "push", "origin", "main"), check=False)
    raise ControlError("unknown command profile")


def next_prompt() -> str:
    status = status_payload(mode="tui")
    blocked = [item for item in status.get("predecessors") or [] if not item.get("pass")]
    if blocked:
        names = ", ".join(str(item.get("slice")) for item in blocked)
        return f"STOP: predecessor completion is missing or not in base ancestry: {names}."
    return (
        f"Current phase is {status['phase']} at {status['head']}. "
        f"Only perform: {status.get('next_allowed_action')}. "
        "Advance at most one outer state transition and return exact evidence."
    )


def _lease_command(args: argparse.Namespace) -> None:
    if args.lease_action == "acquire":
        result = acquire_lease()
    elif args.lease_action == "takeover":
        result = acquire_lease(takeover=True, expected_generation=args.generation)
    elif args.lease_action == "heartbeat":
        result = heartbeat_lease(args.generation)
    elif args.lease_action == "release":
        result = release_lease(args.generation)
    else:
        result = lease_status()
    _json_output(
        {
            "pass": result.allowed,
            "reason": result.reason,
            "lease": _public_lease(result.lease),
        }
    )
    if not result.allowed and args.lease_action != "status":
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--mode", choices=("tui", "rpc", "json", "print"), default="tui")

    lease_parser = subparsers.add_parser("lease")
    lease_parser.add_argument(
        "lease_action",
        choices=("status", "acquire", "heartbeat", "release", "takeover"),
    )
    lease_parser.add_argument("--generation")

    guard_parser = subparsers.add_parser("guard")
    guard_parser.add_argument("--tool", required=True)
    guard_parser.add_argument("--path")
    guard_parser.add_argument("--mode", choices=("tui", "rpc", "json", "print"), default="tui")

    verify_parser = subparsers.add_parser("verify-pr")
    verify_parser.add_argument("--pr", type=int, required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--kind", choices=("gate", "implementation"), required=True)
    bootstrap_parser.add_argument("--slice", required=True)
    bootstrap_parser.add_argument("--milestone", required=True)
    bootstrap_parser.add_argument("--branch", required=True)
    bootstrap_parser.add_argument("--base-sha", required=True)
    bootstrap_parser.add_argument("--gate-doc", action="append", default=[])
    bootstrap_parser.add_argument("--allowed-path", action="append", default=[])
    bootstrap_parser.add_argument("--forbidden-path", action="append", default=[])
    bootstrap_parser.add_argument("--include-roadmap", action="store_true")

    record_pr_parser = subparsers.add_parser("record-pr")
    record_pr_parser.add_argument("--pr", type=int, required=True)

    transition_parser = subparsers.add_parser("transition")
    transition_parser.add_argument("--to", required=True, choices=tuple(FORWARD_PHASES))
    transition_parser.add_argument("--candidate")
    transition_parser.add_argument("--rollback-reason")
    transition_parser.add_argument("--review-pass-ref")

    exec_parser = subparsers.add_parser("exec")
    exec_parser.add_argument("--profile", required=True)
    exec_parser.add_argument("arguments", nargs="*")

    subparsers.add_parser("next")
    subparsers.add_parser("policy-check")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            _json_output(status_payload(mode=args.mode))
        elif args.command == "lease":
            if args.lease_action in {"heartbeat", "release", "takeover"} and not args.generation:
                raise ControlError("lease generation is required")
            _lease_command(args)
        elif args.command == "guard":
            allowed, reason = guard_tool(args.tool, path=args.path, mode=args.mode)
            _json_output({"pass": allowed, "reason": reason})
            if not allowed:
                raise SystemExit(2)
        elif args.command == "verify-pr":
            evidence = verify_pr(args.pr)
            _json_output(evidence)
            if not evidence["pass"]:
                raise SystemExit(2)
        elif args.command == "bootstrap":
            state = bootstrap_state(
                kind=args.kind,
                slice_name=args.slice,
                milestone=args.milestone,
                branch=args.branch,
                base_sha=args.base_sha,
                gate_docs=args.gate_doc,
                allowed_paths=args.allowed_path,
                forbidden_paths=args.forbidden_path,
                include_roadmap=args.include_roadmap,
            )
            _json_output({"pass": True, "state": state})
        elif args.command == "record-pr":
            state = record_pr_number(args.pr)
            _json_output({"pass": True, "state": state, "pr_metadata": "pending-control-commit"})
        elif args.command == "transition":
            state = transition_state(
                args.to,
                candidate=args.candidate,
                rollback_reason=args.rollback_reason,
                review_pass_ref=args.review_pass_ref,
            )
            _json_output(
                {
                    "pass": True,
                    "state": state,
                    "pr_metadata": "pending-control-commit",
                }
            )
        elif args.command == "exec":
            completed = execute_profile(args.profile, args.arguments)
            _json_output(
                {
                    "pass": completed.returncode == 0,
                    "profile": args.profile,
                    "stdout": _redact_output(completed.stdout[-20_000:]),
                    "stderr": _redact_output(completed.stderr[-20_000:]),
                    "returncode": completed.returncode,
                }
            )
            if completed.returncode != 0:
                raise SystemExit(completed.returncode)
        elif args.command == "next":
            _json_output({"pass": True, "prompt": next_prompt()})
        elif args.command == "policy-check":
            actual = canonical_policy_hash()
            _json_output(
                {
                    "pass": actual == EXPECTED_POLICY_HASH,
                    "actual_sha256": actual,
                    "expected_sha256": EXPECTED_POLICY_HASH,
                }
            )
            if actual != EXPECTED_POLICY_HASH:
                raise SystemExit(2)
    except ControlError as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
