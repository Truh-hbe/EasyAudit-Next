from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from scripts import easyaudit_agent as agent


def _point_agent_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(agent, "ROOT", root)
    monkeypatch.setattr(agent, "RUNTIME_DIR", root / ".easyaudit" / "runtime")
    monkeypatch.setattr(
        agent,
        "LEASE_PATH",
        root / ".easyaudit" / "runtime" / "omp-agent-lease.json",
    )
    monkeypatch.setattr(
        agent,
        "LEASE_GUARD_PATH",
        root / ".easyaudit" / "runtime" / "omp-agent-lease.guard",
    )


def test_forged_launcher_environment_token_cannot_mint_activation_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_agent_at(monkeypatch, tmp_path)
    token = "f" * 64
    monkeypatch.setenv("EASYAUDIT_OMP_LAUNCH_TOKEN", token)

    proof_path = agent._activation_path(token)
    assert not proof_path.exists()

    with pytest.raises(agent.ControlError, match="activation proof does not exist"):
        agent.consume_activation(token, os.getpid())

    assert not proof_path.exists(), "consumer must never mint launcher authority"


def test_expired_launcher_activation_proof_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _point_agent_at(monkeypatch, tmp_path)
    token = "e" * 64
    child_pid = os.getpid()
    proof_path = agent._write_activation_record(
        token,
        launcher_pid=child_pid,
        expected_child_pid=child_pid,
    )
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    proof["created_epoch"] = time.time() - agent.ACTIVATION_TTL_SECONDS - 1.0
    proof_path.write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(agent.ControlError, match="activation proof has expired"):
        agent.consume_activation(token, child_pid)

    persisted = json.loads(proof_path.read_text(encoding="utf-8"))
    assert persisted["consumed"] is False
