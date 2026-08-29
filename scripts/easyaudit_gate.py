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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / ".easyaudit" / "development-state.json"
DEFAULT_OUTPUT = ROOT / ".easyaudit-review"
DEFAULT_FINALIZATION_ALLOWED_PATHS = [".easyaudit/development-state.json"]
VALID_PHASES = {
    "UNSET",
    "GATE_DRAFT",
    "GATE_REVIEW",
    "IMPLEMENTATION",
    "FINAL_REVIEW",
    "MERGE_AUTHORIZED",
    "MERGED",
}


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

    if data.get("schema_version") != 1:
        raise GateError("development-state schema_version must be 1")
    phase = data.get("phase")
    if phase not in VALID_PHASES:
        raise GateError(f"unsupported development phase: {phase!r}")
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


def _evaluate_scope(
    state: dict[str, Any],
    evidence: GitEvidence,
    github_context: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    github_context = github_context or {}
    scope = state.get("scope") or {}
    allowed = [str(item) for item in scope.get("allowed_paths") or []]
    forbidden = [str(item) for item in scope.get("forbidden_paths") or []]

    forbidden_hits = [path for path in evidence.changed_files if _matches(path, forbidden)]
    outside_allowed = [
        path
        for path in evidence.changed_files
        if allowed and not _matches(path, allowed)
    ]

    gate_docs = [str(item) for item in state.get("gate_docs") or []]
    missing_gate_docs = [path for path in gate_docs if not (ROOT / path).is_file()]

    fixed_head = state.get("fixed_head")
    candidate_heads = {evidence.head_sha, github_context.get("pr_head_sha")}
    fixed_head_matches = fixed_head in (None, "") or fixed_head in candidate_heads

    phase = state.get("phase")
    candidate_head = str(github_context.get("pr_head_sha") or evidence.head_sha)
    fixed_head_exists = False
    fixed_head_ancestor = False
    fixed_head_resolved: str | None = None
    finalization_allowed = [
        str(item)
        for item in state.get("finalization_allowed_paths")
        or DEFAULT_FINALIZATION_ALLOWED_PATHS
    ]
    finalization_changed_files: list[str] = []
    finalization_outside_allowed: list[str] = []

    if phase == "FINAL_REVIEW":
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
                    fixed_head_resolved, candidate_head
                )
                if fixed_head_ancestor:
                    finalization_text = _git(
                        "diff", "--name-only", f"{fixed_head_resolved}..{candidate_head}"
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

    expected_branch = state.get("work_branch")
    candidate_branches = {evidence.branch, github_context.get("pr_head_ref")}
    branch_matches = (
        expected_branch in (None, "")
        or expected_branch in candidate_branches
        or (not evidence.branch and not github_context.get("pr_head_ref"))
    )

    violations: list[str] = []
    if forbidden_hits:
        violations.append(f"forbidden paths changed: {', '.join(forbidden_hits)}")
    if outside_allowed:
        violations.append(f"paths outside allowed scope: {', '.join(outside_allowed)}")
    if missing_gate_docs:
        violations.append(f"missing Gate documents: {', '.join(missing_gate_docs)}")
    if not fixed_head_matches:
        if phase == "FINAL_REVIEW":
            if not fixed_head:
                violations.append(
                    "FINAL_REVIEW requires a non-empty fixed_head; set it to the "
                    "implementation-reviewed executable head"
                )
            elif not fixed_head_exists:
                violations.append(f"fixed_head does not resolve to a commit: {fixed_head}")
            elif not fixed_head_ancestor:
                violations.append(
                    f"fixed_head {fixed_head} is not an ancestor of candidate HEAD "
                    f"{candidate_head}"
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

    return {
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "forbidden_hits": forbidden_hits,
        "outside_allowed": outside_allowed,
        "missing_gate_docs": missing_gate_docs,
        "fixed_head_matches": fixed_head_matches,
        "fixed_head": fixed_head,
        "fixed_head_resolved": fixed_head_resolved,
        "fixed_head_exists": fixed_head_exists,
        "fixed_head_ancestor": fixed_head_ancestor,
        "candidate_head": candidate_head,
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
        "next_allowed_action": state.get("next_allowed_action"),
        "state_fingerprint": _state_fingerprint(state_path or DEFAULT_STATE),
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
    (output / "gate-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "changed-files.txt").write_text(
        "".join(f"{path}\n" for path in evidence.changed_files),
        encoding="utf-8",
    )
    committed_diff = _git(
        "diff", "--no-ext-diff", "--no-color", f"{evidence.base_ref}...HEAD"
    )
    (output / "branch.diff").write_text(
        committed_diff + ("\n" if committed_diff else ""),
        encoding="utf-8",
    )
    working_diff = _git("diff", "--no-ext-diff", "--no-color", "HEAD")
    (output / "working-tree.diff").write_text(
        working_diff + ("\n" if working_diff else ""),
        encoding="utf-8",
    )
    return output


def _validate_bundle(
    output: Path,
    state: dict[str, Any],
    state_path: Path,
    evidence: GitEvidence,
    current_proof: dict[str, Any],
) -> list[str]:
    bundle_path = _bundle_path(output) / "gate-proof.json"
    if not bundle_path.is_file():
        return [f"Review Bundle is missing: {bundle_path.parent}"]

    try:
        bundle_proof = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Review Bundle gate-proof.json is unreadable: {exc}"]

    violations: list[str] = []
    bundle_git = bundle_proof.get("git") or {}
    current_git = current_proof["git"]
    if bundle_proof.get("schema_version") != 1:
        violations.append("Review Bundle has an unsupported schema_version")
    if bundle_proof.get("state_fingerprint") != _state_fingerprint(state_path):
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
    if not (bundle_proof.get("scope") or {}).get("pass"):
        violations.append("Review Bundle contains a failing Gate scope proof")
    if not current_proof["scope"].get("pass"):
        violations.append("current Gate scope is failing")
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
