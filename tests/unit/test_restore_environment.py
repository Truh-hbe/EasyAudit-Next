"""restore.sh environment against stub `docker`/`git`: call order, isolation, no volume deletion."""

import hashlib
import json
import os
import shutil
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
REVISION = "20261003_0014"

DOCKER_STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$STUB_CALLS"
args=" $* "
[ "$1" = inspect ] && { echo true; exit 0; }
fail_if() { [ -n "${!1:-}" ] && { echo "stub: $1" >&2; exit 1; }; return 0; }
case "$args" in
  *" ps -q api"*) ;;
  *" ps -q "*) echo cid ;;
  *" db-tool psql "*)
    case "$args" in
      *"count(*)"*) echo 0 ;;
      *"version_num"*) echo "$STUB_DB_REVISION" ;;
    esac ;;
  *" db-tool pg_restore "*) cat >/dev/null; fail_if STUB_FAIL_PGRESTORE ;;
  *" object-tool "*lsf*) ;;
  *" object-tool "*copy*) fail_if STUB_FAIL_COPY ;;
  *" migrate alembic "*) echo "$STUB_ALEMBIC_REVISION" ;;
  *" easyaudit-next verify-evidence"*)
    fail_if STUB_FAIL_APP
    if [ -n "${STUB_READY:-}" ]; then
      touch "$STUB_READY"
      # Only a backstop against a hung test: the test always releases, and the loop ends then.
      for _ in $(seq 3000); do [ -e "$STUB_READY.release" ] && break; sleep 0.1; done
    fi ;;
  *" up -d --wait gateway"*) fail_if STUB_FAIL_GATEWAY ;;
esac
exit 0
"""
GIT_STUB = f"""#!/usr/bin/env bash
case "$*" in
  *"rev-parse HEAD"*) echo "{SHA}" ;;
esac
exit 0
"""
VERIFY_STUB = """#!/usr/bin/env bash
echo "verify.sh $*" >> "$STUB_CALLS"
[ -z "${STUB_FAIL_VERIFY:-}" ] || { echo "verify: live environment is inconsistent" >&2; exit 1; }
"""


@dataclass
class Sandbox:
    root: Path
    calls: Path
    backup: Path

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        full = {
            **os.environ,
            "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "STUB_CALLS": str(self.calls),
            "STUB_DB_REVISION": REVISION,
            "STUB_ALEMBIC_REVISION": REVISION,
            "EASYAUDIT_RELEASE": SHA,
            "EASYAUDIT_SECRETS_DIR": str(self.root / "secrets"),
            "EASYAUDIT_CERTS_DIR": str(self.root / "certs"),
            **env,
        }
        script = self.root / "deploy" / "backup" / "restore.sh"
        return subprocess.run(
            [str(script), "environment", str(self.backup)],
            capture_output=True,
            text=True,
            env=full,
            timeout=60,
        )

    def call_log(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def index(self, fragment: str) -> int:
        matches = [i for i, line in enumerate(self.call_log()) if fragment in line]
        assert matches, f"no call containing {fragment!r} in {self.call_log()}"
        return matches[0]

    def called(self, fragment: str) -> bool:
        return any(fragment in line for line in self.call_log())


def _executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_sandbox(tmp_path: Path, *, degraded: bool) -> Sandbox:
    if os.geteuid() == 0:
        pytest.skip("restore.sh refuses to run as root")
    deploy = tmp_path / "deploy"
    shutil.copytree(ROOT / "deploy" / "backup", deploy / "backup")
    shutil.copy(ROOT / "deploy" / "compose.yaml", deploy / "compose.yaml")
    _executable(deploy / "backup" / "verify.sh", VERIFY_STUB)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "docker", DOCKER_STUB)
    _executable(bin_dir / "git", GIT_STUB)
    secrets, certs = tmp_path / "secrets", tmp_path / "certs"
    secrets.mkdir()
    certs.mkdir()
    for name in (
        "postgres_password",
        "garage_rpc_secret",
        "s3_access_key_id",
        "s3_secret_access_key",
    ):
        (secrets / name).write_text("x")
    for name in ("tls.crt", "tls.key"):
        (certs / name).write_text("x")
    backup = tmp_path / "easyaudit-backup-20261007T000000Z"
    backup.mkdir()
    dump = b"dump"
    (backup / "database.dump").write_bytes(dump)
    manifest = {
        "format_version": 1,
        "backup_timestamp": "2026-10-07T00:00:00Z",
        "release_sha": SHA,
        "alembic_revision": REVISION,
        "database": {
            "file": "database.dump",
            "size_bytes": len(dump),
            "sha256": hashlib.sha256(dump).hexdigest(),
        },
        "objects": [],
        "integrity": "degraded" if degraded else "ok",
        "integrity_problems": ["evidence x: object missing"] if degraded else [],
    }
    (backup / "manifest.json").write_text(json.dumps(manifest))
    return Sandbox(tmp_path, tmp_path / "calls.log", backup)


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return _make_sandbox(tmp_path, degraded=False)


def _assert_nothing_deleted(box: Sandbox) -> None:
    for line in box.call_log():
        assert " down" not in line and "volume" not in line and " rm " not in line, line


def test_successful_restore_opens_the_gateway_only_after_every_check(sandbox: Sandbox) -> None:
    result = sandbox.run()

    assert result.returncode == 0, result.stderr
    assert "RESTORE OK" in result.stdout
    verify = sandbox.index("verify.sh")
    internal = sandbox.index("up -d --wait api web")
    app_check = sandbox.index("easyaudit-next verify-evidence")
    gateway = sandbox.index("up -d --wait gateway")
    assert (
        sandbox.index("pg_restore")
        < sandbox.index("copy /data")
        < verify
        < internal
        < app_check
        < gateway
    )
    assert not sandbox.called(" stop ")
    _assert_nothing_deleted(sandbox)


def test_degraded_backup_is_rejected_before_anything_is_started_or_written(tmp_path: Path) -> None:
    box = _make_sandbox(tmp_path, degraded=True)
    result = box.run()

    assert result.returncode != 0
    assert "degraded backup" in result.stderr
    assert "nothing was written" in result.stderr
    assert not box.called(" up ")
    assert not box.called("pg_restore")
    assert not box.called(" build")


@pytest.mark.parametrize("failure", ["STUB_FAIL_PGRESTORE", "STUB_FAIL_COPY"])
def test_copy_failure_stops_before_any_entrypoint(sandbox: Sandbox, failure: str) -> None:
    result = sandbox.run(**{failure: "1"})

    assert result.returncode != 0
    assert not sandbox.called("verify.sh")
    assert not sandbox.called("up -d --wait api")
    assert not sandbox.called("up -d --wait gateway")
    _assert_nothing_deleted(sandbox)


def test_wrong_alembic_revision_stops_before_verification(sandbox: Sandbox) -> None:
    result = sandbox.run(STUB_ALEMBIC_REVISION="other")

    assert result.returncode != 0
    assert not sandbox.called("verify.sh")
    assert not sandbox.called("up -d --wait api")
    assert not sandbox.called("up -d --wait gateway")


def test_final_verification_failure_never_starts_an_entrypoint(sandbox: Sandbox) -> None:
    result = sandbox.run(STUB_FAIL_VERIFY="1")

    assert result.returncode != 0
    assert "RESTORE OK" not in result.stdout
    assert not sandbox.called("up -d --wait api")
    assert not sandbox.called("up -d --wait gateway")
    assert not sandbox.called(" stop ")
    _assert_nothing_deleted(sandbox)


@pytest.mark.parametrize("failure", ["STUB_FAIL_APP", "STUB_FAIL_GATEWAY"])
def test_post_start_failure_stops_the_entrypoints_and_keeps_the_data(
    sandbox: Sandbox, failure: str
) -> None:
    result = sandbox.run(**{failure: "1"})

    assert result.returncode != 0
    assert "RESTORE OK" not in result.stdout
    assert "stopping gateway, web and api" in result.stderr
    assert "nothing was deleted" in result.stderr
    stop = sandbox.index("stop gateway web api")
    assert stop > sandbox.index("up -d --wait api web")
    if failure == "STUB_FAIL_APP":
        assert not sandbox.called("up -d --wait gateway")
    _assert_nothing_deleted(sandbox)
    assert (sandbox.backup / "manifest.json").is_file()


@pytest.mark.parametrize(("sig", "expected"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_signal_after_entrypoints_started_stops_them(
    sandbox: Sandbox, sig: signal.Signals, expected: int
) -> None:
    ready = sandbox.root / "app-check-running"
    script = sandbox.root / "deploy" / "backup" / "restore.sh"
    process = subprocess.Popen(
        [str(script), "environment", str(sandbox.backup)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            **os.environ,
            "PATH": f"{sandbox.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "STUB_CALLS": str(sandbox.calls),
            "STUB_DB_REVISION": REVISION,
            "STUB_ALEMBIC_REVISION": REVISION,
            "EASYAUDIT_RELEASE": SHA,
            "EASYAUDIT_SECRETS_DIR": str(sandbox.root / "secrets"),
            "EASYAUDIT_CERTS_DIR": str(sandbox.root / "certs"),
            "STUB_READY": str(ready),
        },
        # A pytest started as a background job inherits an ignored SIGINT, and a shell cannot trap
        # a signal that was ignored on entry; the script must see the default disposition.
        preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
    )
    try:
        # restore.sh starts python3 several times before this point; under heavy load that is slow.
        deadline = time.monotonic() + 120
        while not ready.exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        process.send_signal(sig)
        # bash runs the trap once the foreground stub returns; let it return successfully.
        Path(f"{ready}.release").touch()
        stdout, stderr = process.communicate(timeout=120)
    finally:
        process.kill()

    assert process.returncode in (expected, -sig)
    assert "RESTORE OK" not in stdout
    assert "stopping gateway, web and api" in stderr
    assert stderr.count("stopping gateway, web and api") == 1
    sandbox.index("stop gateway web api")
    assert not sandbox.called("up -d --wait gateway")
    _assert_nothing_deleted(sandbox)
    assert (sandbox.backup / "manifest.json").is_file()
