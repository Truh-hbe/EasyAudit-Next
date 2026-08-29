#!/usr/bin/env python3
"""Machine-readable EasyAudit Gate checks and C2C review bundles."""

from __future__ import annotations

import argparse
import fnmatch
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


def _git(*args: str, cwd: Path = ROOT) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GateError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


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


def _evaluate_scope(state: dict[str, Any], evidence: GitEvidence) -> dict[str, Any]:
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
    fixed_head_matches = fixed_head in (None, "", evidence.head_sha)

    expected_branch = state.get("work_branch")
    branch_matches = expected_branch in (None, "", evidence.branch) or not evidence.branch

    violations: list[str] = []
    if forbidden_hits:
        violations.append(f"forbidden paths changed: {', '.join(forbidden_hits)}")
    if outside_allowed:
        violations.append(f"paths outside allowed scope: {', '.join(outside_allowed)}")
    if missing_gate_docs:
        violations.append(f"missing Gate documents: {', '.join(missing_gate_docs)}")
    if not fixed_head_matches:
        violations.append(
            f"HEAD {evidence.head_sha} does not match fixed_head {fixed_head}"
        )
    if not branch_matches:
        violations.append(
            f"branch {evidence.branch!r} does not match work_branch {expected_branch!r}"
        )

    return {
        "allowed_paths": allowed,
        "forbidden_paths": forbidden,
        "forbidden_hits": forbidden_hits,
        "outside_allowed": outside_allowed,
        "missing_gate_docs": missing_gate_docs,
        "fixed_head_matches": fixed_head_matches,
        "branch_matches": branch_matches,
        "violations": violations,
        "pass": not violations,
    }


def _proof(state: dict[str, Any], evidence: GitEvidence) -> dict[str, Any]:
    active = bool(state.get("active"))
    scope_result = _evaluate_scope(state, evidence) if active else {
        "pass": True,
        "violations": [],
        "note": "workflow inactive; scope is not currently machine-enforced",
    }
    return {
        "schema_version": 1,
        "project": state.get("project", "EasyAudit-Next"),
        "active": active,
        "milestone": state.get("milestone"),
        "slice": state.get("slice"),
        "phase": state.get("phase"),
        "next_allowed_action": state.get("next_allowed_action"),
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
        "scope": scope_result,
        "ci_environment": {
            "github_actions": os.getenv("GITHUB_ACTIONS") == "true",
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_number": os.getenv("GITHUB_RUN_NUMBER"),
            "github_event_name": os.getenv("GITHUB_EVENT_NAME"),
            "github_sha": os.getenv("GITHUB_SHA"),
        },
        "authority": {
            "c2c_execution_records_are_final_ci": False,
            "github_actions_is_final_ci_authority": True,
            "merge_requires_explicit_authorization": True,
        },
    }


def _write_bundle(output: Path, state: dict[str, Any], evidence: GitEvidence) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    proof = _proof(state, evidence)
    (output / "gate-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "changed-files.txt").write_text(
        "".join(f"{path}\n" for path in evidence.changed_files),
        encoding="utf-8",
    )
    committed_diff = _git("diff", "--no-ext-diff", "--no-color", f"{evidence.base_ref}...HEAD")
    (output / "branch.diff").write_text(committed_diff + ("\n" if committed_diff else ""), encoding="utf-8")
    working_diff = _git("diff", "--no-ext-diff", "--no-color", "HEAD")
    (output / "working-tree.diff").write_text(
        working_diff + ("\n" if working_diff else ""),
        encoding="utf-8",
    )
    return output


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
        proof = _proof(state, evidence)

        if args.command == "bundle":
            output = _write_bundle(args.output, state, evidence)
            print(str(output))
            return 0 if proof["scope"]["pass"] else 2

        violations = list(proof["scope"]["violations"])
        if args.require_clean and not evidence.working_tree_clean:
            violations.append("working tree is not clean")
        result = {
            "active": True,
            "phase": state.get("phase"),
            "pass": not violations,
            "violations": violations,
            "head_sha": evidence.head_sha,
            "base_ref": evidence.base_ref,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not violations else 2
    except GateError as exc:
        print(f"Gate error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
