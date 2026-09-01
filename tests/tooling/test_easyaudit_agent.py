from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from scripts import easyaudit_agent as agent
from scripts import easyaudit_gate as gate

POLICY = {
    "schema_version": 1,
    "policy_id": "easyaudit-workflow-policy-v1",
    "required_checks": {
        "main": {
            "source": "versioned-contract",
            "contexts": ["check", "frontend", "browser-acceptance"],
        }
    },
    "slice_predecessors": {
        "M6.1b-private-infrastructure-qualification": [
            "M6.1a-recovery-contract-tooling",
            "process-omp-agent-control-plane-implementation",
        ],
        "M6-ops-operational-readiness": ["M6.1b-private-infrastructure-qualification"],
    },
    "protected_paths": [
        ".easyaudit/development-state.json",
        ".easyaudit/workflow-policy.json",
    ],
    "policy_change_protocol": "separate-reviewed-policy-seed",
}


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def base_state(
    *,
    phase: str = "IMPLEMENTATION",
    slice_name: str = "process-omp-agent-control-plane-implementation",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active": True,
        "project": "EasyAudit-Next",
        "milestone": "PROCESS",
        "slice": slice_name,
        "phase": phase,
        "base": {"branch": "main", "sha": "base-sha"},
        "work_branch": "codex/control",
        "pr": {"number": 99},
        "gate_docs": [],
        "candidate_kind": "executable",
        "scope": {
            "allowed_paths": ["docs/**", ".easyaudit/development-state.json"],
            "forbidden_paths": ["src/**", ".easyaudit/workflow-policy.json"],
        },
        "fixed_head": None,
        "docs_review_head": None,
        "finalization_allowed_paths": [".easyaudit/development-state.json"],
        "next_allowed_action": "test",
    }


def init_repo(path: Path, state: dict[str, Any] | None = None) -> str:
    run_git(path, "init", "-b", "main")
    run_git(path, "config", "user.email", "agent-test@example.invalid")
    run_git(path, "config", "user.name", "Agent Test")
    write_json(path / ".easyaudit" / "development-state.json", state or base_state())
    write_json(path / ".easyaudit" / "workflow-policy.json", POLICY)
    (path / "docs").mkdir()
    (path / "docs" / "allowed.md").write_text("ok\n", encoding="utf-8")
    run_git(path, "add", ".")
    run_git(path, "commit", "-m", "initial")
    return run_git(path, "rev-parse", "HEAD")


def point_agent_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(agent, "ROOT", root)
    monkeypatch.setattr(agent, "STATE_PATH", root / ".easyaudit" / "development-state.json")
    monkeypatch.setattr(agent, "POLICY_PATH", root / ".easyaudit" / "workflow-policy.json")
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


def point_gate_at(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(gate, "ROOT", root)


def test_launcher_activation_proof_requires_current_token_and_stable_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("EASYAUDIT_OMP_LAUNCH_TOKEN", "a" * 64)
    monkeypatch.setattr(
        agent,
        "_OWNER_OVERRIDE",
        agent.Owner("omp-session", "/tmp/session.jsonl", 1234, "host"),
    )
    proof = agent.prove_activation()
    assert proof["session_id"] == "omp-session"
    assert proof["host_pid"] == 1234
    assert agent._activation_path("a" * 64).is_file()

    monkeypatch.delenv("EASYAUDIT_OMP_LAUNCH_TOKEN")
    with pytest.raises(agent.ControlError, match="launcher token"):
        agent.prove_activation()


def test_committed_policy_matches_candidate_external_hash() -> None:
    assert agent.canonical_policy_hash() == agent.EXPECTED_POLICY_HASH


def test_project_skill_and_prompt_templates_are_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    skill = root / ".omp" / "skills" / "easyaudit-control-plane" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: easyaudit-control-plane\n")
    assert "Use for every planning, mutation, review, merge, deployment" in text
    for reference in (
        "process-omp-agent-control-plane.md",
        "process-omp-agent-control-plane-acceptance.md",
    ):
        assert reference in text

    prompts = root / ".omp" / "prompts"
    expected = {
        "ea-status.md",
        "ea-gate-draft.md",
        "ea-gate-review.md",
        "ea-address-findings.md",
        "ea-final-review.md",
        "ea-merge.md",
        "ea-next.md",
    }
    assert {path.name for path in prompts.glob("*.md")} == expected
    for path in prompts.glob("*.md"):
        prompt = path.read_text(encoding="utf-8")
        assert prompt.startswith("---\n")
        assert "description:" in prompt
        assert "do not" in prompt.lower() or "without mutation" in prompt.lower()
    combined = (prompts / "ea-gate-draft.md").read_text(encoding="utf-8")
    assert "do not implement executable" in combined.lower()
    assert "review, authorize, merge" in combined.lower()


def test_read_only_tools_cannot_escape_repo_or_read_runtime_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    assert agent.guard_tool("read", path="docs/allowed.md", mode="tui")[0] is True
    assert agent.guard_tool("read", path=".env", mode="tui")[0] is False
    assert agent.guard_tool("ls", path=".git", mode="tui")[0] is False
    assert agent.guard_tool("find", path=".easyaudit/runtime", mode="tui")[0] is False
    assert agent.guard_tool("read", path=".easyaudit/runtime/lease.json", mode="tui")[0] is False
    with pytest.raises(agent.ControlError, match="outside the repository"):
        agent.guard_tool("read", path=str(tmp_path.parent / "secret"), mode="tui")


def test_no_lease_blocks_all_shell_and_unknown_mutating_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")

    assert agent.guard_tool("ea_status", path=None, mode="tui")[0] is True
    assert agent.guard_tool("bash", path=None, mode="tui")[0] is False
    assert agent.guard_tool("ast_edit", path="docs/allowed.md", mode="tui")[0] is False
    assert agent.guard_tool("third_party_writer", path=None, mode="tui")[0] is False


def test_writer_guard_allows_scope_but_protects_policy_roots_and_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")
    acquired = agent.acquire_lease()
    assert acquired.allowed is True
    generation = str(acquired.lease["generation_nonce"])

    assert agent.guard_tool("edit", path="docs/allowed.md", mode="tui")[0] is True
    assert agent.guard_tool("edit", path="src/domain.py", mode="tui")[0] is False
    assert (
        agent.guard_tool(
            "edit",
            path=".easyaudit/development-state.json",
            mode="tui",
        )[0]
        is False
    )
    assert agent.guard_tool("write", path=".easyaudit/workflow-policy.json", mode="tui")[0] is False
    assert agent.guard_tool("bash", path=None, mode="tui")[0] is False
    assert agent.release_lease(generation).allowed is True


def test_symlink_escape_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    outside = tmp_path.parent / f"outside-{tmp_path.name}.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (tmp_path / "docs" / "escape").symlink_to(outside)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")
    acquired = agent.acquire_lease()
    assert acquired.allowed is True

    with pytest.raises(agent.ControlError, match="outside the repository"):
        agent.guard_tool("edit", path="docs/escape", mode="tui")


def test_rpc_without_host_guard_is_read_only_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")
    monkeypatch.delenv("EASYAUDIT_OMP_RPC_BASH_GUARDED", raising=False)
    assert agent.acquire_lease().allowed is True

    assert agent.guard_tool("edit", path="docs/allowed.md", mode="rpc")[0] is False
    monkeypatch.setenv("EASYAUDIT_OMP_RPC_BASH_GUARDED", "1")
    assert agent.guard_tool("edit", path="docs/allowed.md", mode="rpc")[0] is False


def test_stable_omp_owner_survives_short_lived_helper_processes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    source_root = Path(__file__).resolve().parents[2]
    common = [
        sys.executable,
        str(source_root / "scripts" / "easyaudit_agent.py"),
        "--owner-session",
        "stable-omp-session",
        "--owner-pid",
        str(os.getpid()),
        "--owner-host",
        socket.gethostname(),
    ]
    environment = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "EASYAUDIT_REPO_ROOT": str(tmp_path),
    }

    acquired = subprocess.run(
        [*common, "lease", "acquire"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    generation = json.loads(acquired.stdout)["lease"]["generation_nonce"]
    status = subprocess.run(
        [*common, "lease", "status"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(status.stdout)["pass"] is True
    subprocess.run(
        [*common, "lease", "heartbeat", "--generation", generation],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [*common, "guard", "--tool", "edit", "--path", "docs/allowed.md"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [*common, "lease", "release", "--generation", generation],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_writer_lease_is_single_process_and_generation_safe(tmp_path: Path) -> None:
    init_repo(tmp_path)
    source_root = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "EASYAUDIT_REPO_ROOT": str(tmp_path),
        "PI_SESSION_ID": "session-a",
    }
    holder_code = """
import json, time
from scripts import easyaudit_agent as agent
result = agent.acquire_lease()
print(json.dumps(result.lease), flush=True)
time.sleep(30)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        lease = json.loads(holder.stdout.readline())
        generation = lease["generation_nonce"]
        contender_env = {**environment, "PI_SESSION_ID": "session-b"}
        contender = subprocess.run(
            [
                sys.executable,
                str(source_root / "scripts" / "easyaudit_agent.py"),
                "lease",
                "acquire",
            ],
            env=contender_env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert contender.returncode == 2
        persisted = json.loads(
            (tmp_path / ".easyaudit" / "runtime" / "omp-agent-lease.json").read_text()
        )
        assert persisted["generation_nonce"] == generation
    finally:
        holder.terminate()
        holder.wait(timeout=5)


def test_takeover_requires_dead_owner_stale_heartbeat_and_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")
    first = agent.acquire_lease()
    generation = str(first.lease["generation_nonce"])
    lease_path = tmp_path / ".easyaudit" / "runtime" / "omp-agent-lease.json"
    lease = json.loads(lease_path.read_text(encoding="utf-8"))

    monkeypatch.setenv("PI_SESSION_ID", "session-b")
    assert not agent.acquire_lease(takeover=True, expected_generation=generation).allowed

    lease["pid"] = 99_999_999
    lease["heartbeat_epoch"] = time.time()
    write_json(lease_path, lease)
    assert not agent.acquire_lease(takeover=True, expected_generation=generation).allowed

    lease["heartbeat_epoch"] = 0
    write_json(lease_path, lease)
    assert not agent.acquire_lease(takeover=True, expected_generation="wrong").allowed
    taken = agent.acquire_lease(takeover=True, expected_generation=generation)
    assert taken.allowed is True
    assert taken.lease["generation_nonce"] != generation


def test_remote_owner_takeover_requires_stale_generation_and_human_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")
    first = agent.acquire_lease()
    generation = str(first.lease["generation_nonce"])
    lease_path = tmp_path / ".easyaudit" / "runtime" / "omp-agent-lease.json"
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    lease["hostname"] = "remote-host"
    lease["heartbeat_epoch"] = 0
    write_json(lease_path, lease)

    monkeypatch.setenv("PI_SESSION_ID", "session-b")
    assert not agent.acquire_lease(
        takeover=True,
        expected_generation=generation,
    ).allowed
    recovered = agent.acquire_lease(
        takeover=True,
        expected_generation=generation,
        remote_owner_confirmed=True,
    )
    assert recovered.allowed is True


def test_old_generation_cannot_release_new_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setenv("PI_SESSION_ID", "session-a")
    first = agent.acquire_lease()
    old_generation = str(first.lease["generation_nonce"])
    assert agent.release_lease(old_generation).allowed is True
    second = agent.acquire_lease()
    new_generation = str(second.lease["generation_nonce"])
    assert old_generation != new_generation
    assert agent.release_lease(old_generation).allowed is False
    assert agent.heartbeat_lease(old_generation).allowed is False
    assert agent.release_lease(new_generation).allowed is True


def test_gate_bootstrap_creates_only_typed_docs_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inactive = base_state(phase="MERGED", slice_name="previous")
    inactive["active"] = False
    inactive["work_branch"] = None
    base = init_repo(tmp_path, inactive)
    run_git(tmp_path, "checkout", "-b", "codex/new-gate")
    point_agent_at(monkeypatch, tmp_path)

    proposed = agent.bootstrap_state(
        kind="gate",
        slice_name="new-slice",
        milestone="M7",
        branch="codex/new-gate",
        base_sha=base,
        gate_docs=(
            "docs/architecture/new-slice.md",
            "docs/architecture/new-slice-acceptance.md",
        ),
        allowed_paths=(),
        forbidden_paths=("src/**",),
        include_roadmap=True,
    )

    assert proposed["phase"] == "GATE_DRAFT"
    assert proposed["candidate_kind"] == "docs-only"
    assert proposed["scope"]["allowed_paths"] == [
        ".easyaudit/development-state.json",
        "docs/architecture/new-slice.md",
        "docs/architecture/new-slice-acceptance.md",
        "docs/architecture/roadmap.md",
    ]
    assert ".easyaudit/workflow-policy.json" in proposed["scope"]["forbidden_paths"]
    assert (tmp_path / "docs" / "architecture" / "new-slice.md").is_file()


def test_implementation_bootstrap_rejects_policy_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inactive = base_state(phase="MERGED", slice_name="previous")
    inactive["active"] = False
    inactive["work_branch"] = None
    base = init_repo(tmp_path, inactive)
    gate_doc = tmp_path / "docs" / "architecture" / "gate.md"
    gate_doc.parent.mkdir(parents=True, exist_ok=True)
    gate_doc.write_text("# Gate\n", encoding="utf-8")
    run_git(tmp_path, "add", "docs/architecture/gate.md")
    run_git(tmp_path, "commit", "-m", "gate")
    base = run_git(tmp_path, "rev-parse", "HEAD")
    run_git(tmp_path, "checkout", "-b", "codex/implementation")
    point_agent_at(monkeypatch, tmp_path)

    with pytest.raises(agent.ControlError, match="Scope must be derived"):
        agent.bootstrap_state(
            kind="implementation",
            slice_name="process-omp-agent-control-plane-implementation",
            milestone="PROCESS",
            branch="codex/implementation",
            base_sha=base,
            gate_docs=("docs/architecture/gate.md",),
            allowed_paths=(".easyaudit/workflow-policy.json",),
            forbidden_paths=(),
            include_roadmap=False,
        )


def test_implementation_bootstrap_derives_scope_from_merged_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate_doc = "docs/architecture/reviewed-gate.md"
    inactive = base_state(phase="MERGED", slice_name="gate-slice")
    inactive["active"] = False
    inactive["work_branch"] = None
    inactive["gate_docs"] = [gate_doc]
    inactive["approved_implementation"] = {
        "slice": "approved-implementation",
        "gate_docs": [gate_doc],
        "allowed_paths": [
            ".easyaudit/development-state.json",
            "scripts/approved.py",
        ],
        "forbidden_paths": [
            ".easyaudit/workflow-policy.json",
            "src/**",
        ],
    }
    init_repo(tmp_path, inactive)
    reviewed = tmp_path / gate_doc
    reviewed.parent.mkdir(parents=True, exist_ok=True)
    reviewed.write_text("# Reviewed Gate\n", encoding="utf-8")
    run_git(tmp_path, "add", gate_doc)
    run_git(tmp_path, "commit", "-m", "merge Gate")
    base = run_git(tmp_path, "rev-parse", "HEAD")
    run_git(tmp_path, "checkout", "-b", "codex/approved-implementation")
    point_agent_at(monkeypatch, tmp_path)

    proposed = agent.bootstrap_state(
        kind="implementation",
        slice_name="approved-implementation",
        milestone="M7",
        branch="codex/approved-implementation",
        base_sha=base,
        gate_docs=(gate_doc,),
        allowed_paths=(),
        forbidden_paths=(),
        include_roadmap=False,
        dry_run=True,
    )

    assert proposed["scope"] == {
        "allowed_paths": inactive["approved_implementation"]["allowed_paths"],
        "forbidden_paths": inactive["approved_implementation"]["forbidden_paths"],
    }
    assert "slice" not in proposed["scope"]
    assert proposed["implementation_authorization_commit"]


def test_record_pr_is_typed_and_non_overwritable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = base_state()
    state["pr"] = {"number": None}
    init_repo(tmp_path, state)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setattr(agent, "_gate_check", lambda *args, **kwargs: True)

    assert agent.record_pr_number(42)["pr"] == {"number": 42}
    with pytest.raises(agent.ControlError, match="only be bound once"):
        agent.record_pr_number(42)
    with pytest.raises(agent.ControlError, match="only be bound once"):
        agent.record_pr_number(43)


def test_state_publication_validates_before_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = base_state()
    init_repo(tmp_path, state)
    point_agent_at(monkeypatch, tmp_path)
    old_bytes = agent.STATE_PATH.read_bytes()
    proposed = json.loads(json.dumps(state))
    proposed["next_allowed_action"] = "validated change"

    monkeypatch.setattr(agent, "_gate_check", lambda *args, **kwargs: False)
    with pytest.raises(agent.ControlError, match="proposed state failed"):
        agent._atomic_write_state(old_bytes, proposed)
    assert agent.STATE_PATH.read_bytes() == old_bytes

    monkeypatch.setattr(agent, "_gate_check", lambda *args, **kwargs: True)
    real_replace = os.replace

    def fail_before_publication(source: str | Path, destination: str | Path) -> None:
        if Path(destination) == agent.STATE_PATH:
            raise OSError("fault before rename")
        real_replace(source, destination)

    monkeypatch.setattr(agent.os, "replace", fail_before_publication)
    with pytest.raises(OSError, match="fault before rename"):
        agent._atomic_write_state(old_bytes, proposed)
    assert agent.STATE_PATH.read_bytes() == old_bytes


def test_transition_rejects_phase_jump_and_scope_escalation() -> None:
    old = base_state(phase="IMPLEMENTATION")
    jumped = json.loads(json.dumps(old))
    jumped["phase"] = "MERGE_AUTHORIZED"
    with pytest.raises(agent.ControlError, match="illegal phase transition"):
        agent.validate_state_transition(old, jumped)

    widened = json.loads(json.dumps(old))
    widened["phase"] = "FINAL_REVIEW"
    widened["fixed_head"] = "candidate"
    widened["scope"]["allowed_paths"].append("src/**")
    with pytest.raises(agent.ControlError, match="widen allowed_paths"):
        agent.validate_state_transition(old, widened)


def test_post_merge_transition_allows_only_rebaseline_metadata() -> None:
    old = base_state(phase="MERGE_AUTHORIZED")
    old["fixed_head"] = "candidate"
    proposed = json.loads(json.dumps(old))
    proposed["phase"] = "MERGED"
    proposed["active"] = False
    proposed["base"] = {"branch": "main", "sha": "merge-commit"}
    proposed["work_branch"] = None
    agent.validate_state_transition(old, proposed)

    escalated = json.loads(json.dumps(proposed))
    escalated["scope"]["allowed_paths"].append("src/**")
    with pytest.raises(agent.ControlError, match="widen allowed_paths"):
        agent.validate_state_transition(old, escalated)


def test_rollback_requires_reason_and_clears_candidate() -> None:
    old = base_state(phase="FINAL_REVIEW")
    old["fixed_head"] = "candidate"
    proposed = json.loads(json.dumps(old))
    proposed["phase"] = "IMPLEMENTATION"
    proposed["fixed_head"] = None
    with pytest.raises(agent.ControlError, match="requires a bounded reason"):
        agent.validate_state_transition(old, proposed)


def test_predecessor_requires_completed_main_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    predecessor = base_state(
        phase="MERGED",
        slice_name="M6.1b-private-infrastructure-qualification",
    )
    predecessor["active"] = False
    predecessor["work_branch"] = None
    initial = init_repo(tmp_path, predecessor)
    state = base_state(slice_name="M6-ops-operational-readiness")
    state["base"]["sha"] = initial
    write_json(tmp_path / ".easyaudit" / "development-state.json", state)
    run_git(tmp_path, "add", ".easyaudit/development-state.json")
    run_git(tmp_path, "commit", "-m", "start M6-Ops")
    point_agent_at(monkeypatch, tmp_path)

    evidence = agent.verify_predecessors()
    assert evidence == [
        {
            "slice": "M6.1b-private-infrastructure-qualification",
            "completion_commit": initial,
            "base_ancestor": True,
            "head_ancestor": True,
            "pass": True,
        }
    ]

    state["base"]["sha"] = f"{initial}^"
    write_json(tmp_path / ".easyaudit" / "development-state.json", state)
    evidence = agent.verify_predecessors()
    assert evidence[0]["pass"] is False


def test_control_output_redacts_environment_and_url_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONTROL_SECRET_TOKEN", "SECRET_SENTINEL")
    rendered = agent._redact_output(
        "SECRET_SENTINEL https://alice:password@example.invalid Cookie: session=value"
    )
    assert "SECRET_SENTINEL" not in rendered
    assert "alice:password" not in rendered
    assert "session=value" not in rendered


def test_command_profiles_reject_shell_escape() -> None:
    with pytest.raises(agent.ControlError, match="shell control tokens"):
        agent.execute_profile("git-commit", ["message", ";"])
    with pytest.raises(agent.ControlError, match="unknown command profile"):
        agent.execute_profile("arbitrary", [])


def test_review_reference_binds_zero_finding_pass_to_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = "a" * 40
    monkeypatch.setattr(agent, "_repository_slug", lambda: "owner/repo")
    payload = {
        "body": (f"fixed candidate = {candidate}\nP0 = 0\nP1 = 0\nP2 = 0\nRESULT = PASS\n"),
        "author_association": "OWNER",
        "user": {"login": "maintainer"},
        "html_url": "https://example.invalid/comment/1",
    }
    monkeypatch.setattr(
        agent,
        "_run",
        lambda argv, check=False: subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(payload),
            "",
        ),
    )

    evidence = agent.verify_review_reference(45, candidate, "comment:1")
    assert evidence["candidate"] == candidate
    assert evidence["result"] == "PASS"

    payload["body"] = payload["body"].replace("P1 = 0", "P1 = 1")
    with pytest.raises(agent.ControlError, match="zero-finding PASS"):
        agent.verify_review_reference(45, candidate, "comment:1")


def test_merge_authorization_binds_review_and_exact_remote_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = "a" * 40
    control = "b" * 40
    state = base_state(phase="FINAL_REVIEW")
    state["fixed_head"] = candidate
    write_json(tmp_path / ".easyaudit" / "development-state.json", state)
    point_agent_at(monkeypatch, tmp_path)
    monkeypatch.setattr(agent, "_git", lambda *args, **kwargs: control)
    monkeypatch.setattr(agent, "_is_ancestor", lambda ancestor, descendant: True)
    monkeypatch.setattr(agent, "_finalization_chain_is_valid", lambda current, head: True)
    monkeypatch.setattr(
        agent,
        "verify_pr",
        lambda pr: {
            "pass": True,
            "pr": {"state": "OPEN", "isDraft": False, "headRefOid": control},
        },
    )
    review = {
        "reference": "comment:1",
        "candidate": candidate,
        "result": "PASS",
        "p0": 0,
        "p1": 0,
        "p2": 0,
    }
    monkeypatch.setattr(agent, "verify_review_reference", lambda pr, head, ref: review)
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        agent,
        "_atomic_write_state",
        lambda old, proposed: captured.update(proposed),
    )

    result = agent.transition_state(
        "MERGE_AUTHORIZED",
        candidate=None,
        rollback_reason=None,
        review_pass_ref="comment:1",
    )
    assert result["review_evidence"] == review
    assert result["authorized_control_parent"] == control

    monkeypatch.setattr(
        agent,
        "verify_pr",
        lambda pr: {
            "pass": True,
            "pr": {"state": "OPEN", "isDraft": False, "headRefOid": "c" * 40},
        },
    )
    with pytest.raises(agent.ControlError, match="exact-head PR evidence"):
        agent.transition_state(
            "MERGE_AUTHORIZED",
            candidate=None,
            rollback_reason=None,
            review_pass_ref="comment:1",
        )


def test_required_check_contract_rejects_github_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "load_trusted_policy", lambda: POLICY)
    monkeypatch.setattr(
        agent,
        "_remote_required_contexts",
        lambda base: ({"check"}, "github-branch-protection"),
    )

    def fake_run(argv: tuple[str, ...], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        payload = {
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "headRefName": "codex/example",
            "baseRefName": "main",
            "headRefOid": "a" * 40,
            "baseRefOid": "b" * 40,
            "mergedAt": None,
            "url": "https://example.invalid/pr/1",
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    monkeypatch.setattr(agent, "_run", fake_run)
    with pytest.raises(agent.ControlError, match="drift"):
        agent.verify_pr(1)


def test_required_check_contract_falls_back_to_trusted_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "load_trusted_policy", lambda: POLICY)
    monkeypatch.setattr(agent, "_remote_required_contexts", lambda base: (None, "unavailable"))

    def fake_run(argv: tuple[str, ...], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ("gh", "pr", "view"):
            payload = {
                "state": "OPEN",
                "isDraft": False,
                "mergeable": "MERGEABLE",
                "headRefName": "codex/example",
                "baseRefName": "main",
                "headRefOid": "a" * 40,
                "baseRefOid": "b" * 40,
                "mergedAt": None,
                "url": "https://example.invalid/pr/1",
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")
        checks = [
            {"name": name, "state": "SUCCESS", "bucket": "pass", "link": ""}
            for name in ("check", "frontend", "browser-acceptance")
        ]
        return subprocess.CompletedProcess(argv, 0, json.dumps(checks), "")

    monkeypatch.setattr(agent, "_run", fake_run)
    result = agent.verify_pr(1)
    assert result["pass"] is True
    assert result["required_source"] == "trusted-base-versioned-contract"


def test_pr_metadata_sync_detects_current_and_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"value": "Initial"}

    def fake_run(argv: tuple[str, ...], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if argv[:3] == ("gh", "pr", "view"):
            return subprocess.CompletedProcess(argv, 0, json.dumps({"body": body["value"]}), "")
        if argv[:3] == ("gh", "pr", "edit"):
            body["value"] = argv[-1]
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)

    monkeypatch.setattr(agent, "_run", fake_run)
    monkeypatch.setattr(agent, "_git", lambda *args, **kwargs: "a" * 40)
    state = base_state()
    assert agent.sync_pr_metadata(state) == "current"
    assert "phase=IMPLEMENTATION" in body["value"]

    def failing_run(
        argv: tuple[str, ...],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, "", "failed")

    monkeypatch.setattr(agent, "_run", failing_run)
    assert agent.sync_pr_metadata(state) == "drift"


def test_gate_rejects_dirty_final_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    point_gate_at(monkeypatch, tmp_path)
    state = base_state(phase="FINAL_REVIEW")
    state["fixed_head"] = "candidate"
    evidence = gate.GitEvidence(
        base_ref="base",
        merge_base="base",
        head_sha="control",
        head_tree="tree",
        branch="codex/control",
        ahead=2,
        behind=0,
        changed_files=(".easyaudit/development-state.json",),
        working_tree_clean=False,
        status_lines=(" M docs/allowed.md",),
    )
    monkeypatch.setattr(gate, "_git", lambda *args, **kwargs: "candidate")
    monkeypatch.setattr(gate, "_git_is_ancestor", lambda ancestor, descendant: True)

    result = gate._evaluate_scope(state, evidence)
    assert result["pass"] is False
    assert "FINAL_REVIEW requires a clean working tree" in result["violations"]


def test_gate_rejects_policy_change_outside_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_gate_at(monkeypatch, tmp_path)
    state = base_state()
    evidence = gate.GitEvidence(
        base_ref="base",
        merge_base="base",
        head_sha="head",
        head_tree="tree",
        branch="codex/control",
        ahead=1,
        behind=0,
        changed_files=(".easyaudit/workflow-policy.json",),
        working_tree_clean=True,
        status_lines=(),
    )

    result = gate._evaluate_scope(state, evidence)
    assert result["pass"] is False
    assert any("workflow policy changed" in value for value in result["violations"])


def test_gate_allows_exact_policy_seed_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_repo(tmp_path)
    point_gate_at(monkeypatch, tmp_path)
    state = base_state(slice_name=gate.POLICY_SEED_SLICE)
    state["scope"] = {
        "allowed_paths": [
            ".easyaudit/development-state.json",
            ".easyaudit/workflow-policy.json",
        ],
        "forbidden_paths": ["src/**"],
    }
    evidence = gate.GitEvidence(
        base_ref="base",
        merge_base="base",
        head_sha="head",
        head_tree="tree",
        branch="codex/control",
        ahead=1,
        behind=0,
        changed_files=(
            ".easyaudit/development-state.json",
            ".easyaudit/workflow-policy.json",
        ),
        working_tree_clean=True,
        status_lines=(),
    )

    result = gate._evaluate_scope(state, evidence)
    assert result["pass"] is True
    assert result["policy_violations"] == []
