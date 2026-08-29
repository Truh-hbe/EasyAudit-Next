from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import easyaudit_gate as gate


def evidence(changed_files: tuple[str, ...]) -> gate.GitEvidence:
    return gate.GitEvidence(
        base_ref="base",
        merge_base="base-sha",
        head_sha="head-sha",
        head_tree="tree-sha",
        branch="codex/example",
        ahead=2,
        behind=0,
        changed_files=changed_files,
        working_tree_clean=True,
        status_lines=(),
    )


def test_scope_rejects_forbidden_and_outside_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "scope": {
            "allowed_paths": ["docs/architecture/**", ".easyaudit/development-state.json"],
            "forbidden_paths": ["src/**", "web/**"],
        },
        "gate_docs": [],
        "fixed_head": None,
        "work_branch": "codex/example",
    }

    result = gate._evaluate_scope(
        state,
        evidence(("docs/architecture/gate.md", "src/domain.py", "README.md")),
    )

    assert result["pass"] is False
    assert result["forbidden_hits"] == ["src/domain.py"]
    assert result["outside_allowed"] == ["src/domain.py", "README.md"]


def test_scope_accepts_gate_docs_and_fixed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    gate_doc = tmp_path / "docs" / "architecture" / "gate.md"
    gate_doc.parent.mkdir(parents=True)
    gate_doc.write_text("# Gate\n", encoding="utf-8")
    state = {
        "scope": {
            "allowed_paths": ["docs/architecture/**"],
            "forbidden_paths": ["src/**", "web/**"],
        },
        "gate_docs": ["docs/architecture/gate.md"],
        "fixed_head": "head-sha",
        "work_branch": "codex/example",
    }

    result = gate._evaluate_scope(
        state,
        evidence(("docs/architecture/gate.md",)),
    )

    assert result["pass"] is True
    assert result["violations"] == []


def test_scope_accepts_fixed_pr_head_when_actions_checkout_is_merge_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "scope": {"allowed_paths": ["docs/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": "candidate-sha",
        "work_branch": "codex/example",
    }
    merge_ref_evidence = gate.GitEvidence(
        base_ref="base",
        merge_base="base-sha",
        head_sha="synthetic-merge-sha",
        head_tree="tree-sha",
        branch="",
        ahead=2,
        behind=0,
        changed_files=("docs/gate.md",),
        working_tree_clean=True,
        status_lines=(),
    )

    result = gate._evaluate_scope(
        state,
        merge_ref_evidence,
        {"pr_head_sha": "candidate-sha", "pr_head_ref": "codex/example"},
    )

    assert result["pass"] is True
    assert result["fixed_head_matches"] is True
    assert result["branch_matches"] is True


def test_final_review_rejects_missing_fixed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "phase": "FINAL_REVIEW",
        "scope": {"allowed_paths": ["docs/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": None,
        "work_branch": "codex/example",
    }

    result = gate._evaluate_scope(state, evidence(("docs/gate.md",)))

    assert result["pass"] is False
    assert "FINAL_REVIEW requires a non-empty fixed_head" in result["violations"][0]


def test_final_review_accepts_metadata_only_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "phase": "FINAL_REVIEW",
        "scope": {"allowed_paths": ["docs/**", ".easyaudit/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": "implementation-sha",
        "finalization_allowed_paths": [".easyaudit/development-state.json"],
        "work_branch": "codex/example",
    }

    def fake_git(*args: str, cwd: Path | None = None) -> str:
        if args[:2] == ("rev-parse", "--verify"):
            return "implementation-sha"
        if args[:2] == ("diff", "--name-only"):
            return ".easyaudit/development-state.json"
        raise AssertionError(args)

    monkeypatch.setattr(gate, "_git", fake_git)
    monkeypatch.setattr(gate, "_git_is_ancestor", lambda ancestor, descendant: True)

    result = gate._evaluate_scope(
        state,
        evidence((".easyaudit/development-state.json",)),
    )

    assert result["pass"] is True
    assert result["fixed_head_ancestor"] is True
    assert result["candidate_head"] == "implementation-sha"
    assert result["control_head"] == "head-sha"
    assert result["finalization_outside_allowed"] == []


def test_final_review_rejects_executable_change_after_fixed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "phase": "FINAL_REVIEW",
        "scope": {"allowed_paths": ["scripts/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": "implementation-sha",
        "finalization_allowed_paths": [".easyaudit/development-state.json"],
        "work_branch": "codex/example",
    }

    def fake_git(*args: str, cwd: Path | None = None) -> str:
        if args[:2] == ("rev-parse", "--verify"):
            return "implementation-sha"
        if args[:2] == ("diff", "--name-only"):
            return "scripts/easyaudit_gate.py"
        raise AssertionError(args)

    monkeypatch.setattr(gate, "_git", fake_git)
    monkeypatch.setattr(gate, "_git_is_ancestor", lambda ancestor, descendant: True)

    result = gate._evaluate_scope(state, evidence(("scripts/easyaudit_gate.py",)))

    assert result["pass"] is False
    assert result["finalization_outside_allowed"] == ["scripts/easyaudit_gate.py"]
    assert any("non-finalization files changed" in item for item in result["violations"])


def test_final_review_uses_actual_pull_request_head_for_ancestor_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "phase": "FINAL_REVIEW",
        "scope": {"allowed_paths": [".easyaudit/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": "implementation-sha",
        "finalization_allowed_paths": [".easyaudit/development-state.json"],
        "work_branch": "codex/example",
    }
    descendants: list[str] = []

    def fake_git(*args: str, cwd: Path | None = None) -> str:
        if args[:2] == ("rev-parse", "--verify"):
            return "implementation-sha"
        if args[:2] == ("diff", "--name-only"):
            return ".easyaudit/development-state.json"
        raise AssertionError(args)

    def fake_ancestor(ancestor: str, descendant: str) -> bool:
        descendants.append(descendant)
        return True

    monkeypatch.setattr(gate, "_git", fake_git)
    monkeypatch.setattr(gate, "_git_is_ancestor", fake_ancestor)
    result = gate._evaluate_scope(
        state,
        evidence((".easyaudit/development-state.json",)),
        {"pr_head_sha": "actual-pr-head", "pr_head_ref": "codex/example"},
    )

    assert result["pass"] is True
    assert descendants == ["actual-pr-head"]


@pytest.mark.parametrize("phase", ["FINAL_REVIEW", "MERGE_AUTHORIZED"])
def test_control_phases_reject_missing_fixed_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state = {
        "phase": phase,
        "scope": {"allowed_paths": [".easyaudit/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": "",
        "work_branch": "codex/example",
    }

    result = gate._evaluate_scope(state, evidence((".easyaudit/state.json",)))

    assert result["pass"] is False
    assert any(
        f"{phase} requires a non-empty fixed_head" in item
        for item in result["violations"]
    )


def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit_git(repo: Path, message: str) -> str:
    _run_git(
        repo,
        "-c",
        "user.name=Gate Test",
        "-c",
        "user.email=gate@example.com",
        "commit",
        "-m",
        message,
    )
    return _run_git(repo, "rev-parse", "HEAD")


def test_final_review_uses_real_candidate_and_control_commit_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    state_path = repo / ".easyaudit" / "development-state.json"
    state_path.parent.mkdir()
    state_path.write_text('{"phase":"IMPLEMENTATION"}\n', encoding="utf-8")
    _run_git(repo, "add", ".")
    base_sha = _commit_git(repo, "base")

    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    _run_git(repo, "add", "candidate.txt")
    candidate_sha = _commit_git(repo, "candidate")

    state_path.write_text(
        '{"phase":"FINAL_REVIEW","fixed_head":"' + candidate_sha + '"}\n',
        encoding="utf-8",
    )
    _run_git(repo, "add", ".easyaudit/development-state.json")
    control_sha = _commit_git(repo, "final review state")

    monkeypatch.setattr(gate, "ROOT", repo)
    state = {
        "phase": "FINAL_REVIEW",
        "scope": {
            "allowed_paths": ["candidate.txt", ".easyaudit/**"],
            "forbidden_paths": [],
        },
        "gate_docs": [],
        "fixed_head": candidate_sha,
        "finalization_allowed_paths": [".easyaudit/development-state.json"],
        "work_branch": None,
    }
    git_evidence = gate.GitEvidence(
        base_ref=base_sha,
        merge_base=base_sha,
        head_sha=control_sha,
        head_tree=_run_git(repo, "rev-parse", "HEAD^{tree}"),
        branch=_run_git(repo, "branch", "--show-current"),
        ahead=2,
        behind=0,
        changed_files=(".easyaudit/development-state.json", "candidate.txt"),
        working_tree_clean=True,
        status_lines=(),
    )

    result = gate._evaluate_scope(state, git_evidence)

    assert result["pass"] is True
    assert result["candidate_head"] == candidate_sha
    assert result["control_head"] == control_sha
    assert result["finalization_changed_files"] == [
        ".easyaudit/development-state.json"
    ]


def _bundle_state() -> dict[str, object]:
    return {
        "active": True,
        "project": "EasyAudit-Next",
        "milestone": "M5",
        "slice": "tooling",
        "phase": "IMPLEMENTATION",
        "scope": {"allowed_paths": ["docs/**"], "forbidden_paths": []},
        "gate_docs": [],
        "fixed_head": None,
        "work_branch": "codex/example",
    }


def _install_synthetic_bundle(
    bundle_dir: Path,
    proof: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = {name: f"{name}\n" for name in gate.BUNDLE_ARTIFACT_NAMES}
    monkeypatch.setattr(gate, "_bundle_artifacts", lambda evidence, proof: artifacts)
    bundle_dir.mkdir(exist_ok=True)
    (bundle_dir / "gate-proof.json").write_text(
        json.dumps(proof), encoding="utf-8"
    )
    for name, contents in artifacts.items():
        (bundle_dir / name).write_text(contents, encoding="utf-8")


def test_bundle_validation_rejects_stale_head_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state_path = tmp_path / "development-state.json"
    state_path.write_text('{"phase":"IMPLEMENTATION"}\n', encoding="utf-8")
    state = _bundle_state()
    current_evidence = evidence(("docs/gate.md",))
    current_proof = gate._proof(state, current_evidence, state_path)
    bundle_dir = tmp_path / ".easyaudit-review"
    _install_synthetic_bundle(bundle_dir, current_proof, monkeypatch)
    stale_proof = json.loads(json.dumps(current_proof))
    stale_proof["git"]["head_sha"] = "old-head"
    state_path.write_text('{"phase":"FINAL_REVIEW"}\n', encoding="utf-8")
    (bundle_dir / "gate-proof.json").write_text(
        json.dumps(stale_proof), encoding="utf-8"
    )

    violations = gate._validate_bundle(
        bundle_dir, state, state_path, current_evidence, current_proof
    )

    assert "Review Bundle does not match the current development state" in violations
    assert "Review Bundle does not match the current HEAD" in violations


def test_bundle_validation_accepts_current_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state_path = tmp_path / "development-state.json"
    state_path.write_text('{"phase":"IMPLEMENTATION"}\n', encoding="utf-8")
    state = _bundle_state()
    current_evidence = evidence(("docs/gate.md",))
    current_proof = gate._proof(state, current_evidence, state_path)
    bundle_dir = tmp_path / ".easyaudit-review"
    _install_synthetic_bundle(bundle_dir, current_proof, monkeypatch)

    assert gate._validate_bundle(
        bundle_dir, state, state_path, current_evidence, current_proof
    ) == []


@pytest.mark.parametrize("artifact", gate.BUNDLE_ARTIFACT_NAMES)
def test_bundle_validation_rejects_missing_or_modified_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    state_path = tmp_path / "development-state.json"
    state_path.write_text('{"phase":"IMPLEMENTATION"}\n', encoding="utf-8")
    state = _bundle_state()
    current_evidence = evidence(("docs/gate.md",))
    current_proof = gate._proof(state, current_evidence, state_path)

    bundle_dir = tmp_path / ".easyaudit-review"
    _install_synthetic_bundle(bundle_dir, current_proof, monkeypatch)
    artifact_path = bundle_dir / artifact
    artifact_path.unlink()

    violations = gate._validate_bundle(
        bundle_dir, state, state_path, current_evidence, current_proof
    )
    assert f"Review Bundle is missing artifact: {artifact_path}" in violations

    _install_synthetic_bundle(bundle_dir, current_proof, monkeypatch)
    artifact_path.write_text("old or modified evidence\n", encoding="utf-8")
    violations = gate._validate_bundle(
        bundle_dir, state, state_path, current_evidence, current_proof
    )
    assert f"Review Bundle artifact is stale or modified: {artifact}" in violations


def test_generated_bundle_rejects_old_candidate_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.name", "Gate Test")
    _run_git(repo, "config", "user.email", "gate@example.com")
    state_path = repo / ".easyaudit" / "development-state.json"
    state_path.parent.mkdir()
    state = {
        "schema_version": 1,
        "active": True,
        "project": "EasyAudit-Next",
        "milestone": "M5",
        "slice": "tooling",
        "phase": "IMPLEMENTATION",
        "scope": {
            "allowed_paths": ["candidate.txt", ".easyaudit/**"],
            "forbidden_paths": [],
        },
        "gate_docs": [],
        "fixed_head": None,
        "work_branch": None,
    }
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    base_sha = _commit_git(repo, "base")
    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    _run_git(repo, "add", "candidate.txt")
    _commit_git(repo, "candidate")

    monkeypatch.setattr(gate, "ROOT", repo)
    # The test owns a temporary repository. Do not let a surrounding PR
    # workflow's GitHub event substitute the real PR head for this repo.
    monkeypatch.setattr(gate, "_github_pr_context", lambda: {})
    evidence_now = gate._collect_git_evidence(base_sha)
    proof_now = gate._proof(state, evidence_now, state_path)
    bundle_dir = repo / ".easyaudit-review"
    gate._write_bundle(bundle_dir, state, evidence_now, state_path)
    assert gate._validate_bundle(
        bundle_dir, state, state_path, evidence_now, proof_now
    ) == []

    (bundle_dir / "candidate.diff").write_text("old candidate evidence\n", encoding="utf-8")
    violations = gate._validate_bundle(
        bundle_dir, state, state_path, evidence_now, proof_now
    )
    assert "Review Bundle artifact is stale or modified: candidate.diff" in violations


def test_load_state_rejects_unknown_phase(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "phase": "MAGIC"}),
        encoding="utf-8",
    )

    with pytest.raises(gate.GateError, match="unsupported development phase"):
        gate._load_state(state_path)


def test_proof_marks_github_actions_as_final_ci_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    state = {
        "active": False,
        "project": "EasyAudit-Next",
        "phase": "UNSET",
    }

    proof = gate._proof(state, evidence(()))

    assert proof["authority"]["c2c_execution_records_are_final_ci"] is False
    assert proof["authority"]["github_actions_is_final_ci_authority"] is True
    assert proof["github"]["actions"] is True
