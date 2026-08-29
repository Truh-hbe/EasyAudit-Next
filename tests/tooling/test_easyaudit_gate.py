from __future__ import annotations

import json
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
