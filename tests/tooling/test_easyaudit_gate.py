from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "easyaudit_gate.py"


def load_gate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("easyaudit_gate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(module: ModuleType, changed_files: tuple[str, ...]):
    return module.GitEvidence(
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


def test_scope_rejects_forbidden_and_outside_allowed(tmp_path: Path) -> None:
    module = load_gate_module()
    module.ROOT = tmp_path
    state = {
        "scope": {
            "allowed_paths": ["docs/architecture/**", ".easyaudit/development-state.json"],
            "forbidden_paths": ["src/**", "web/**"],
        },
        "gate_docs": [],
        "fixed_head": None,
        "work_branch": "codex/example",
    }

    result = module._evaluate_scope(
        state,
        evidence(module, ("docs/architecture/gate.md", "src/domain.py", "README.md")),
    )

    assert result["pass"] is False
    assert result["forbidden_hits"] == ["src/domain.py"]
    assert result["outside_allowed"] == ["src/domain.py", "README.md"]


def test_scope_accepts_gate_docs_and_fixed_head(tmp_path: Path) -> None:
    module = load_gate_module()
    module.ROOT = tmp_path
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

    result = module._evaluate_scope(
        state,
        evidence(module, ("docs/architecture/gate.md",)),
    )

    assert result["pass"] is True
    assert result["violations"] == []


def test_load_state_rejects_unknown_phase(tmp_path: Path) -> None:
    module = load_gate_module()
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 1, "phase": "MAGIC"}),
        encoding="utf-8",
    )

    with pytest.raises(module.GateError, match="unsupported development phase"):
        module._load_state(state_path)


def test_proof_marks_github_actions_as_final_ci_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_gate_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    state = {
        "active": False,
        "project": "EasyAudit-Next",
        "phase": "UNSET",
    }

    proof = module._proof(state, evidence(module, ()))

    assert proof["authority"]["c2c_execution_records_are_final_ci"] is False
    assert proof["authority"]["github_actions_is_final_ci_authority"] is True
    assert proof["ci_environment"]["github_actions"] is True
