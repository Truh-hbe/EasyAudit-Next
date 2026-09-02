#!/usr/bin/env python3
"""Machine-readable EasyAudit Gate checks and C2C review bundles."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

ROOT = Path(os.getenv("EASYAUDIT_REPO_ROOT", Path(__file__).resolve().parents[1])).resolve()
DEFAULT_STATE = ROOT / ".easyaudit" / "development-state.json"
DEFAULT_OUTPUT = ROOT / ".easyaudit-review"
DEFAULT_FINALIZATION_ALLOWED_PATHS = [".easyaudit/development-state.json"]
BUNDLE_ARTIFACT_NAMES = (
    "changed-files.txt",
    "branch.diff",
    "candidate.diff",
    "control.diff",
    "working-tree.diff",
)
VALID_PHASES = {
    "UNSET",
    "GATE_DRAFT",
    "GATE_REVIEW",
    "IMPLEMENTATION",
    "FINAL_REVIEW",
    "MERGE_AUTHORIZED",
    "MERGED",
}
VALID_CANDIDATE_KINDS = {"executable", "docs-only"}
DOCS_ONLY_STATE_PATH = ".easyaudit/development-state.json"
WORKFLOW_POLICY_PATH = ".easyaudit/workflow-policy.json"
EXPECTED_WORKFLOW_POLICY_HASH = (
    "31e7c9d4aa8b9f61c20b1d95b85f948ceb919d1d91938c80c5b2006748780857"
)
POLICY_SEED_SLICE = "process-omp-agent-control-plane-policy-seed"


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitEvidence:
    base_ref: str
    merge_base: str
    head_sha: str
    head_tree: str
    branch: str
    ahead: int
    behind: int
    changed_files: tuple[str, ...]
    working_tree_clean: bool
    status_lines: tuple[str, ...]


def _git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd or ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GateError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _git_is_ancestor(ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def _state_fingerprint(path: Path) -> str | None:
    try:
        contents = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(contents).hexdigest()


def _bundle_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateError(f"state file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GateError(f"invalid JSON state file: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise GateError("development-state must contain a JSON object")
    data = cast(dict[str, Any], data)
    if data.get("schema_version") != 1:
        raise GateError("development-state schema_version must be 1")
    phase = data.get("phase")
    if phase not in VALID_PHASES:
        raise GateError(f"unsupported development phase: {phase!r}")
    candidate_kind = data.get("candidate_kind", "executable")
    if candidate_kind not in VALID_CANDIDATE_KINDS:
        raise GateError(f"unsupported candidate kind: {candidate_kind!r}")
    return data


def _resolve_base(state: dict[str, Any], override: str | None) -> str:
    if override:
        return override
    base = state.get("base") or {}
    if base.get("sha"):
        return str(base["sha"])
    if base.get("branch"):
        return str(base["branch"])
    raise GateError("no base ref available; set base.sha/base.branch or pass --base")


def _github_pr_context() -> dict[str, str | None]:
    context: dict[str, str | None] = {
        "event_name": os.getenv("GITHUB_EVENT_NAME"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_number": os.getenv("GITHUB_RUN_NUMBER"),
        "checkout_sha": os.getenv("GITHUB_SHA"),
        "pr_head_sha": None,
        "pr_base_sha": None,
        "pr_head_ref": os.getenv("GITHUB_HEAD_REF"),
        "pr_base_ref": os.getenv("GITHUB_BASE_REF"),
    }
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return context
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return context
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        return context
    head = pull_request.get("head") or {}
    base = pull_request.get("base") or {}
    context["pr_head_sha"] = head.get("sha")
    context["pr_base_sha"] = base.get("sha")
    context["pr_head_ref"] = head.get("ref") or context["pr_head_ref"]
    context["pr_base_ref"] = base.get("ref") or context["pr_base_ref"]
    return context


def _collect_git_evidence(base_ref: str) -> GitEvidence:
    head_sha = _git("rev-parse", "HEAD")
    head_tree = _git("rev-parse", "HEAD^{tree}")
    merge_base = _git("merge-base", base_ref, "HEAD")
    counts = _git("rev-list", "--left-right", "--count", f"{base_ref}...HEAD").split()
    if len(counts) != 2:
        raise GateError("unexpected git rev-list count output")
    behind, ahead = (int(value) for value in counts)
    changed_text = _git("diff", "--name-only", f"{base_ref}...HEAD")
    changed_files = tuple(line for line in changed_text.splitlines() if line)
    status_text = _git("status", "--porcelain=v1")
    status_lines = tuple(line for line in status_text.splitlines() if line)
    branch = _git("branch", "--show-current")
    return GitEvidence(
        base_ref=base_ref,
        merge_base=merge_base,
        head_sha=head_sha,
        head_tree=head_tree,
        branch=branch,
        ahead=ahead,
        behind=behind,
        changed_files=changed_files,
        working_tree_clean=not status_lines,
        status_lines=status_lines,
    )


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _load_workflow_policy() -> tuple[dict[str, Any] | None, str | None]:
    path = ROOT / WORKFLOW_POLICY_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, dict):
        return None, None
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return value, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _trusted_main_ref() -> str | None:
    for ref in ("refs/remotes/origin/main", "refs/heads/main"):
        completed = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=ROOT,
            check=False,
        )
        if completed.returncode == 0:
            return ref
    return None


def _completion_commit(slice_name: str, trusted_main: str) -> str | None:
    try:
        commits = _git(
            "log",
            "--format=%H",
            trusted_main,
            "--",
            DOCS_ONLY_STATE_PATH,
        )
    except GateError:
        return None
    for commit in commits.splitlines():
        completed = subprocess.run(
            ["git", "show", f"{commit}:{DOCS_ONLY_STATE_PATH}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
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


def _docs_only_path_allowed(path: str) -> bool:
    return path == DOCS_ONLY_STATE_PATH or path.startswith("docs/")


def _docs_only_scope_pattern_allowed(pattern: str) -> bool:
    if pattern == DOCS_ONLY_STATE_PATH:
        return True
    if not pattern.startswith("docs/"):
        return False
    if pattern.startswith("/") or "\\" in pattern:
        return False
    return ".." not in pattern.split("/")


def _evaluate_scope(
    state: dict[str, Any],
    evidence: GitEvidence,
    github_context: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    github_context = github_context or {}
    scope = state.get("scope") or {}
    allowed = [str(item) for item in scope.get("allowed_paths") or []]
    forbidden = [str(item) for item in scope.get("forbidden_paths") or []]

    candidate_kind = str(state.get("candidate_kind") or "executable")
    phase = state.get("phase")
    control_head = str(github_context.get("pr_head_sha") or evidence.head_sha)
    control_changed_files = list(evidence.changed_files)
    control_changed_files_error: str | None = None
    if (
        candidate_kind == "docs-only"
        and github_context.get("pr_head_sha")
        and github_context.get("pr_head_sha") != evidence.head_sha
    ):
        try:
            control_text = _git(
                "diff", "--name-only", f"{evidence.base_ref}...{control_head}"
            )
            control_changed_files = [
                line for line in control_text.splitlines() if line
            ]
        except GateError as exc:
            control_changed_files_error = str(exc)

    forbidden_hits = [path for path in control_changed_files if _matches(path, forbidden)]
    outside_allowed = [
        path
        for path in control_changed_files
        if allowed and not _matches(path, allowed)
    ]

    gate_docs = [str(item) for item in state.get("gate_docs") or []]
    missing_gate_docs = [path for path in gate_docs if not (ROOT / path).is_file()]

    fixed_head = state.get("fixed_head")
    candidate_heads = {evidence.head_sha, github_context.get("pr_head_sha")}
    fixed_head_matches = fixed_head in (None, "") or fixed_head in candidate_heads

    candidate_head = control_head
    fixed_head_exists = False
    fixed_head_ancestor = False
    fixed_head_resolved: str | None = None
    docs_review_head = state.get("docs_review_head")
    docs_review_head_matches = True
    docs_review_head_exists = False
    docs_review_head_ancestor = False
    docs_review_head_resolved: str | None = None
    finalization_allowed = [
        str(item)
        for item in state.get("finalization_allowed_paths")
        or DEFAULT_FINALIZATION_ALLOWED_PATHS
    ]
    finalization_changed_files: list[str] = []
    finalization_outside_allowed: list[str] = []
    docs_only_scope_violations: list[str] = []
    policy_violations: list[str] = []
    predecessor_evidence: list[dict[str, Any]] = []

    policy_is_present_or_changed = (
        (ROOT / WORKFLOW_POLICY_PATH).is_file()
        or WORKFLOW_POLICY_PATH in control_changed_files
    )
    if state.get("active") is True and policy_is_present_or_changed:
        policy, policy_hash = _load_workflow_policy()
        if policy is None or policy_hash != EXPECTED_WORKFLOW_POLICY_HASH:
            policy_violations.append("trusted workflow policy is missing or has the wrong hash")
        else:
            current_slice = str(state.get("slice") or "")
            if current_slice != POLICY_SEED_SLICE:
                if WORKFLOW_POLICY_PATH in control_changed_files:
                    policy_violations.append(
                        "workflow policy changed outside the separate policy-seed slice"
                    )
                if any(_matches(WORKFLOW_POLICY_PATH, [pattern]) for pattern in allowed):
                    policy_violations.append(
                        "ordinary active scope must not allow workflow-policy changes"
                    )
            configured = policy.get("slice_predecessors") or {}
            predecessors = (
                configured.get(current_slice, []) if isinstance(configured, dict) else []
            )
            if not isinstance(predecessors, list):
                policy_violations.append("workflow predecessor contract is invalid")
            elif predecessors:
                trusted_main = _trusted_main_ref()
                base_sha = str((state.get("base") or {}).get("sha") or "")
                if trusted_main is None:
                    policy_violations.append("trusted main ref is unavailable")
                else:
                    for predecessor in predecessors:
                        if not isinstance(predecessor, str):
                            policy_violations.append("workflow predecessor name is invalid")
                            continue
                        completion = _completion_commit(predecessor, trusted_main)
                        base_ancestor = bool(
                            completion and base_sha and _git_is_ancestor(completion, base_sha)
                        )
                        head_ancestor = bool(
                            completion and _git_is_ancestor(completion, control_head)
                        )
                        passed = bool(completion and base_ancestor and head_ancestor)
                        predecessor_evidence.append(
                            {
                                "slice": predecessor,
                                "completion_commit": completion,
                                "base_ancestor": base_ancestor,
                                "head_ancestor": head_ancestor,
                                "pass": passed,
                            }
                        )
                        if not passed:
                            policy_violations.append(
                                "required predecessor is not completed in base/main ancestry: "
                                + predecessor
                            )

    if candidate_kind == "docs-only":
        if fixed_head not in (None, ""):
            fixed_head_matches = False

        invalid_scope_patterns = [
            pattern
            for pattern in allowed
            if not _docs_only_scope_pattern_allowed(pattern)
        ]
        if invalid_scope_patterns:
            docs_only_scope_violations.append(
                "docs-only allowed_paths expand the process-owned allowlist: "
                + ", ".join(invalid_scope_patterns)
            )
        invalid_finalization_patterns = [
            pattern
            for pattern in finalization_allowed
            if pattern != DOCS_ONLY_STATE_PATH
        ]
        if invalid_finalization_patterns:
            docs_only_scope_violations.append(
                "docs-only finalization_allowed_paths must contain only "
                f"{DOCS_ONLY_STATE_PATH}: "
                + ", ".join(invalid_finalization_patterns)
            )
        process_outside_allowed = [
            path for path in control_changed_files if not _docs_only_path_allowed(path)
        ]
        if process_outside_allowed:
            docs_only_scope_violations.append(
                "docs-only process allowlist rejects changed paths: "
                + ", ".join(process_outside_allowed)
            )

        if phase == "GATE_DRAFT":
            docs_review_head_matches = docs_review_head in (None, "")
        elif phase in {"GATE_REVIEW", "MERGE_AUTHORIZED"}:
            if not docs_review_head:
                docs_review_head_matches = False
            else:
                try:
                    docs_review_head_resolved = _git(
                        "rev-parse", "--verify", f"{docs_review_head}^{{commit}}"
                    )
                except GateError:
                    docs_review_head_resolved = None
                docs_review_head_exists = docs_review_head_resolved is not None
                if docs_review_head_exists:
                    docs_review_head_ancestor = _git_is_ancestor(
                        docs_review_head_resolved, control_head
                    )
                    if docs_review_head_ancestor:
                        finalization_text = _git(
                            "diff",
                            "--name-only",
                            f"{docs_review_head_resolved}..{control_head}",
                        )
                        finalization_changed_files = [
                            line for line in finalization_text.splitlines() if line
                        ]
                        finalization_outside_allowed = [
                            path
                            for path in finalization_changed_files
                            if not _matches(path, finalization_allowed)
                        ]
                docs_review_head_matches = (
                    docs_review_head_exists
                    and docs_review_head_ancestor
                    and not finalization_outside_allowed
                )
            candidate_head = docs_review_head_resolved or control_head
        else:
            docs_review_head_matches = False
            candidate_head = docs_review_head_resolved or control_head

    if candidate_kind != "docs-only" and phase in {"FINAL_REVIEW", "MERGE_AUTHORIZED"}:
        if not fixed_head:
            fixed_head_matches = False
        else:
            try:
                fixed_head_resolved = _git(
                    "rev-parse", "--verify", f"{fixed_head}^{{commit}}"
                )
            except GateError:
                fixed_head_resolved = None
            fixed_head_exists = fixed_head_resolved is not None
            if fixed_head_exists:
                fixed_head_ancestor = _git_is_ancestor(
                    fixed_head_resolved, control_head
                )
                if fixed_head_ancestor:
                    finalization_text = _git(
                        "diff", "--name-only", f"{fixed_head_resolved}..{control_head}"
                    )
                    finalization_changed_files = [
                        line for line in finalization_text.splitlines() if line
                    ]
                    finalization_outside_allowed = [
                        path
                        for path in finalization_changed_files
                        if not _matches(path, finalization_allowed)
                    ]
            fixed_head_matches = (
                fixed_head_exists
                and fixed_head_ancestor
                and not finalization_outside_allowed
            )
            candidate_head = fixed_head_resolved or control_head

    expected_branch = state.get("work_branch")
    candidate_branches = {evidence.branch, github_context.get("pr_head_ref")}
    branch_matches = (
        expected_branch in (None, "")
        or expected_branch in candidate_branches
        or (not evidence.branch and not github_context.get("pr_head_ref"))
    )

    violations: list[str] = []
    if control_changed_files_error:
        violations.append(
            "could not determine actual PR-head changes: " + control_changed_files_error
        )
    if forbidden_hits:
        violations.append(f"forbidden paths changed: {', '.join(forbidden_hits)}")
    if outside_allowed:
        violations.append(f"paths outside allowed scope: {', '.join(outside_allowed)}")
    if missing_gate_docs:
        violations.append(f"missing Gate documents: {', '.join(missing_gate_docs)}")
    if candidate_kind == "docs-only":
        violations.extend(docs_only_scope_violations)
        if not fixed_head_matches:
            violations.append(
                "docs-only candidates must keep fixed_head empty; "
                f"found {fixed_head!r}"
            )
        if not docs_review_head_matches:
            if phase == "GATE_DRAFT":
                violations.append("docs-only GATE_DRAFT must not set docs_review_head")
            elif phase in {"GATE_REVIEW", "MERGE_AUTHORIZED"}:
                if not docs_review_head:
                    violations.append(
                        f"{phase} requires a non-empty docs_review_head"
                    )
                elif not docs_review_head_exists:
                    violations.append(
                        "docs_review_head does not resolve to a commit: "
                        + str(docs_review_head)
                    )
                elif not docs_review_head_ancestor:
                    violations.append(
                        f"docs_review_head {docs_review_head} is not an ancestor of "
                        f"control HEAD {control_head}"
                    )
                if finalization_outside_allowed:
                    violations.append(
                        "non-finalization files changed after docs_review_head: "
                        + ", ".join(finalization_outside_allowed)
                    )
            else:
                violations.append(
                    f"docs-only candidate_kind is not valid in phase {phase}"
                )
    elif not fixed_head_matches:
        if phase in {"FINAL_REVIEW", "MERGE_AUTHORIZED"}:
            if not fixed_head:
                violations.append(
                    f"{phase} requires a non-empty fixed_head; set it to the "
                    "implementation-reviewed executable head"
                )
            elif not fixed_head_exists:
                violations.append(f"fixed_head does not resolve to a commit: {fixed_head}")
            elif not fixed_head_ancestor:
                violations.append(
                    f"fixed_head {fixed_head} is not an ancestor of candidate HEAD "
                    f"{control_head}"
                )
            if finalization_outside_allowed:
                violations.append(
                    "non-finalization files changed after fixed_head: "
                    + ", ".join(finalization_outside_allowed)
                )
        else:
            violations.append(
                f"candidate HEAD does not match fixed_head {fixed_head}; "
                f"checkout={evidence.head_sha}, pr_head={github_context.get('pr_head_sha')}"
            )
    if not branch_matches:
        violations.append(
            f"candidate branch does not match work_branch {expected_branch!r}; "
            f"checkout={evidence.branch!r}, pr_head={github_context.get('pr_head_ref')!r}"
        )
    if phase in {"FINAL_REVIEW", "MERGE_AUTHORIZED"} and not evidence.working_tree_clean:
        violations.append(f"{phase} requires a clean working tree")
    violations.extend(policy_violations)

    return {
        "candidate_kind": candidate_kind,
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "forbidden_hits": forbidden_hits,
        "outside_allowed": outside_allowed,
        "control_changed_files": control_changed_files,
        "docs_only_scope_violations": docs_only_scope_violations,
        "policy_violations": policy_violations,
        "predecessor_evidence": predecessor_evidence,
        "missing_gate_docs": missing_gate_docs,
        "fixed_head_matches": fixed_head_matches,
        "fixed_head": fixed_head,
        "fixed_head_resolved": fixed_head_resolved,
        "fixed_head_exists": fixed_head_exists,
        "fixed_head_ancestor": fixed_head_ancestor,
        "docs_review_head": docs_review_head,
        "docs_review_head_resolved": docs_review_head_resolved,
        "docs_review_head_exists": docs_review_head_exists,
        "docs_review_head_ancestor": docs_review_head_ancestor,
        "docs_review_head_matches": docs_review_head_matches,
        "candidate_head": candidate_head,
        "control_head": control_head,
        "finalization_allowed_paths": finalization_allowed,
        "finalization_changed_files": finalization_changed_files,
        "finalization_outside_allowed": finalization_outside_allowed,
        "branch_matches": branch_matches,
        "violations": violations,
        "pass": not violations,
    }


def _proof(
    state: dict[str, Any], evidence: GitEvidence, state_path: Path | None = None
) -> dict[str, Any]:
    active = bool(state.get("active"))
    github_context = _github_pr_context()
    scope_result = (
        _evaluate_scope(state, evidence, github_context)
        if active
        else {
            "pass": True,
            "violations": [],
            "note": "workflow inactive; scope is not currently machine-enforced",
        }
    )
    return {
        "schema_version": 1,
        "project": state.get("project", "EasyAudit-Next"),
        "active": active,
        "milestone": state.get("milestone"),
        "slice": state.get("slice"),
        "phase": state.get("phase"),
        "candidate_kind": state.get("candidate_kind", "executable"),
        "next_allowed_action": state.get("next_allowed_action"),
        "state_fingerprint": _state_fingerprint(
            _bundle_path(state_path or DEFAULT_STATE)
        ),
        "git": {
            "base_ref": evidence.base_ref,
            "merge_base": evidence.merge_base,
            "head_sha": evidence.head_sha,
            "head_tree": evidence.head_tree,
            "branch": evidence.branch,
            "ahead": evidence.ahead,
            "behind": evidence.behind,
            "changed_files": list(evidence.changed_files),
            "changed_file_count": len(evidence.changed_files),
            "working_tree_clean": evidence.working_tree_clean,
            "status_lines": list(evidence.status_lines),
        },
        "github": {
            "actions": os.getenv("GITHUB_ACTIONS") == "true",
            **github_context,
        },
        "scope": scope_result,
        "evidence_refs": {
            "candidate": {
                "base": evidence.base_ref,
                "head": scope_result.get("candidate_head", evidence.head_sha),
            },
            "control": {
                "base": scope_result.get("fixed_head_resolved")
                or scope_result.get("docs_review_head_resolved"),
                "head": scope_result.get("control_head", evidence.head_sha),
            },
            "working_tree": {"base": evidence.head_sha, "head": "WORKTREE"},
        },
        "authority": {
            "c2c_execution_records_are_final_ci": False,
            "github_actions_is_final_ci_authority": True,
            "merge_requires_explicit_authorization": True,
        },
    }


def _write_bundle(
    output: Path,
    state: dict[str, Any],
    evidence: GitEvidence,
    state_path: Path | None = None,
) -> Path:
    output = _bundle_path(output)
    output.mkdir(parents=True, exist_ok=True)
    proof = _proof(state, evidence, state_path)
    artifacts = _bundle_artifacts(evidence, proof)
    # Write every evidence artifact before gate-proof.json. The proof is the
    # completion marker, so an interrupted generation cannot leave a fresh
    # proof beside an older diff and still look like a complete bundle.
    for name, contents in artifacts.items():
        (output / name).write_text(contents, encoding="utf-8")
    (output / "gate-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def _bundle_artifacts(
    evidence: GitEvidence, proof: dict[str, Any]
) -> dict[str, str]:
    """Build the canonical non-proof artifacts for the current evidence."""

    committed_diff = _git(
        "diff", "--no-ext-diff", "--no-color", f"{evidence.base_ref}...HEAD"
    )
    working_diff = _git("diff", "--no-ext-diff", "--no-color", "HEAD")
    scope = proof["scope"]
    candidate_head = str(scope.get("candidate_head") or evidence.head_sha)
    candidate_diff = _git(
        "diff", "--no-ext-diff", "--no-color", f"{evidence.base_ref}...{candidate_head}"
    )
    control_base = scope.get("fixed_head_resolved") or scope.get(
        "docs_review_head_resolved"
    )
    control_head = str(scope.get("control_head") or evidence.head_sha)
    control_diff = ""
    if control_base:
        control_diff = _git(
            "diff", "--no-ext-diff", "--no-color", f"{control_base}..{control_head}"
        )
    return {
        "changed-files.txt": "".join(f"{path}\n" for path in evidence.changed_files),
        "branch.diff": committed_diff + ("\n" if committed_diff else ""),
        "candidate.diff": candidate_diff + ("\n" if candidate_diff else ""),
        "control.diff": control_diff + ("\n" if control_diff else ""),
        "working-tree.diff": working_diff + ("\n" if working_diff else ""),
    }


def _validate_bundle(
    output: Path,
    state: dict[str, Any],
    state_path: Path,
    evidence: GitEvidence,
    current_proof: dict[str, Any],
) -> list[str]:
    output = _bundle_path(output)
    bundle_path = output / "gate-proof.json"
    if not bundle_path.is_file():
        return [f"Review Bundle is missing: {bundle_path.parent}"]

    try:
        bundle_proof = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Review Bundle gate-proof.json is unreadable: {exc}"]

    violations: list[str] = []
    if bundle_proof != current_proof:
        violations.append(
            "Review Bundle gate-proof.json does not match current Git/state evidence"
        )
    bundle_git = bundle_proof.get("git") or {}
    current_git = current_proof["git"]
    if bundle_proof.get("schema_version") != 1:
        violations.append("Review Bundle has an unsupported schema_version")
    if bundle_proof.get("state_fingerprint") != _state_fingerprint(
        _bundle_path(state_path)
    ):
        violations.append("Review Bundle does not match the current development state")
    if bundle_git.get("head_sha") != current_git["head_sha"]:
        violations.append("Review Bundle does not match the current HEAD")
    if bundle_git.get("head_tree") != current_git["head_tree"]:
        violations.append("Review Bundle does not match the current HEAD tree")
    if bundle_git.get("base_ref") != current_git["base_ref"]:
        violations.append("Review Bundle does not match the current base ref")
    if bundle_git.get("branch") != current_git["branch"]:
        violations.append("Review Bundle does not match the current branch")
    if bundle_git.get("changed_files") != current_git["changed_files"]:
        violations.append("Review Bundle changed-files evidence is stale")
    if bundle_git.get("working_tree_clean") != current_git["working_tree_clean"]:
        violations.append("Review Bundle working-tree status is stale")
    if bundle_proof.get("phase") != state.get("phase"):
        violations.append("Review Bundle does not match the current Gate phase")
    if bundle_proof.get("evidence_refs") != current_proof.get("evidence_refs"):
        violations.append("Review Bundle evidence refs are stale")
    bundle_scope = bundle_proof.get("scope") or {}
    current_scope = current_proof["scope"]
    if bundle_scope.get("candidate_head") != current_scope.get("candidate_head"):
        violations.append("Review Bundle does not match the reviewed candidate head")
    if bundle_scope.get("control_head") != current_scope.get("control_head"):
        violations.append("Review Bundle does not match the control HEAD")
    if not bundle_scope.get("pass"):
        violations.append("Review Bundle contains a failing Gate scope proof")
    if not current_proof["scope"].get("pass"):
        violations.append("current Gate scope is failing")
    try:
        expected_artifacts = _bundle_artifacts(evidence, current_proof)
    except GateError as exc:
        violations.append(f"could not rebuild canonical Review Bundle artifacts: {exc}")
    else:
        for name in BUNDLE_ARTIFACT_NAMES:
            artifact_path = output / name
            if not artifact_path.is_file():
                violations.append(f"Review Bundle is missing artifact: {artifact_path}")
                continue
            try:
                actual = artifact_path.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(f"Review Bundle artifact is unreadable ({name}): {exc}")
                continue
            if actual != expected_artifacts[name]:
                violations.append(
                    f"Review Bundle artifact is stale or modified: {name}"
                )
    return violations


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--base", help="override the comparison base ref/SHA")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate the active Gate scope")
    check.add_argument(
        "--require-clean",
        action="store_true",
        help="also fail when the working tree is dirty",
    )
    check.add_argument(
        "--require-bundle",
        action="store_true",
        help="also fail when the Review Bundle is missing or stale",
    )
    check.add_argument(
        "--bundle-output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Review Bundle directory to validate",
    )

    bundle = subparsers.add_parser("bundle", help="generate the C2C review bundle")
    bundle.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        state = _load_state(args.state)
        if args.command == "check" and not state.get("active"):
            print(json.dumps({"active": False, "pass": True, "phase": state.get("phase")}))
            return 0

        base_ref = _resolve_base(state, args.base)
        evidence = _collect_git_evidence(base_ref)
        proof = _proof(state, evidence, args.state)

        if args.command == "bundle":
            output = _write_bundle(
                output=args.output,
                state=state,
                evidence=evidence,
                state_path=args.state,
            )
            print(str(output))
            return 0 if proof["scope"]["pass"] else 2

        violations = list(proof["scope"]["violations"])
        if args.require_clean and not evidence.working_tree_clean:
            violations.append("working tree is not clean")
        if args.require_bundle:
            violations.extend(
                _validate_bundle(args.bundle_output, state, args.state, evidence, proof)
            )
        result = {
            "active": True,
            "phase": state.get("phase"),
            "pass": not violations,
            "violations": violations,
            "head_sha": evidence.head_sha,
            "pr_head_sha": proof["github"].get("pr_head_sha"),
            "base_ref": evidence.base_ref,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not violations else 2
    except GateError as exc:
        print(f"Gate error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
