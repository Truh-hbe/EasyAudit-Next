"""Static guardrails for the production topology in deploy/compose.yaml."""

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "deploy" / "compose.yaml"

# Services allowed to run as root, with the reason. Currently none.
ROOT_EXCEPTIONS: dict[str, str] = {}
RELEASE_IMAGE = re.compile(r"^easyaudit/[a-z-]+:\$\{EASYAUDIT_RELEASE:\?[^}]+\}$")
RELEASE_LABEL = "org.opencontainers.image.revision=${EASYAUDIT_RELEASE:?"
BUILT_SERVICES = ("web", "api", "migrate", "object-storage")
TOOL_SERVICES = ("db-tool", "object-tool")
SECRET_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN|KEY)", re.IGNORECASE)


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE_PATH.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _services(compose: dict[str, Any]) -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = compose["services"]
    return services


def _is_pinned(reference: str) -> bool:
    if "@sha256:" in reference:
        return True
    _, sep, tag = reference.rpartition(":")
    if not sep or "/" in tag or not tag:
        return False
    return "latest" not in tag.lower() and tag.lower() not in {"stable", "alpine", "slim"}


def _dockerfile_bases(dockerfile: Path) -> list[str]:
    bases: list[str] = []
    stages: set[str] = set()
    for line in dockerfile.read_text().splitlines():
        match = re.match(r"\s*FROM\s+(?:--\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
        if match:
            if match.group(1) not in stages:
                bases.append(match.group(1))
            if match.group(2):
                stages.add(match.group(2))
    return bases


def test_expected_services_exist(compose: dict[str, Any]) -> None:
    assert {
        "gateway",
        "web",
        "api",
        "postgres",
        "object-storage",
        "migrate",
        *TOOL_SERVICES,
    } <= set(_services(compose))


def test_only_gateway_publishes_only_443(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        if name != "gateway":
            assert "ports" not in service, f"{name} must not publish ports"
    ports = _services(compose)["gateway"]["ports"]
    assert len(ports) == 1
    published = str(ports[0]["published"])
    assert published in {"443", "${EASYAUDIT_HTTPS_PORT:-443}"}
    assert ports[0].get("host_ip") in (None, "0.0.0.0")


def test_all_images_pinned(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        if "build" in service:
            # Self-built images are tagged by release SHA (never latest/local); see below.
            assert RELEASE_IMAGE.match(service["image"]), f"{name}: built image {service['image']}"
            build = service["build"]
            context = COMPOSE_PATH.parent / build["context"]
            dockerfile = context / build.get("dockerfile", "Dockerfile")
            bases = _dockerfile_bases(dockerfile)
            assert bases, f"{name}: no FROM found in {dockerfile}"
            for base in bases:
                assert _is_pinned(base), f"{name}: {base} in {dockerfile} is not pinned"
        else:
            assert _is_pinned(service["image"]), f"{name}: {service['image']} is not pinned"


def test_built_images_are_tagged_and_labelled_with_the_release(compose: dict[str, Any]) -> None:
    services = _services(compose)
    assert {name for name, service in services.items() if "build" in service} == set(BUILT_SERVICES)
    for name in BUILT_SERVICES:
        image = services[name]["image"]
        assert "latest" not in image and ":local" not in image, name
        assert "${EASYAUDIT_RELEASE:?" in image, f"{name}: tag must require EASYAUDIT_RELEASE"
        labels = services[name]["build"].get("labels", [])
        assert any(label.startswith(RELEASE_LABEL) for label in labels), f"{name}: no label"


def test_tool_services_are_one_shot_and_isolated(compose: dict[str, Any]) -> None:
    services = _services(compose)
    for name in TOOL_SERVICES:
        service = services[name]
        assert service["profiles"] == ["backup"], f"{name}: must not start with the stack"
        assert "ports" not in service, f"{name} must not publish ports"
        assert "build" not in service and "restart" not in service, name
        assert set(service["networks"]) == {"backend"}, name
        assert "depends_on" not in service, name
        assert not service.get("volumes"), f"{name}: mounts are given per run by the scripts"
    assert services["db-tool"]["image"] == services["postgres"]["image"]
    assert services["object-tool"]["image"].startswith("rclone/rclone:")
    assert set(services["db-tool"]["secrets"]) == {"postgres_password"}
    assert set(services["object-tool"]["secrets"]) == {"s3_access_key_id", "s3_secret_access_key"}


def test_data_services_only_on_internal_network(compose: dict[str, Any]) -> None:
    assert compose["networks"]["backend"]["internal"] is True
    assert not compose["networks"]["edge"].get("internal", False)
    services = _services(compose)
    for name in ("postgres", "object-storage", "migrate", *TOOL_SERVICES):
        assert set(services[name]["networks"]) == {"backend"}, name
    assert set(services["api"]["networks"]) == {"edge", "backend"}
    assert set(services["gateway"]["networks"]) == {"edge"}
    assert set(services["web"]["networks"]) == {"edge"}


def test_every_service_is_non_root(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        if name in ROOT_EXCEPTIONS:
            continue
        user = str(service.get("user", ""))
        assert user, f"{name}: user must be set explicitly"
        assert user.split(":")[0] not in {"0", "root"}, f"{name} runs as root"


def test_every_service_drops_capabilities_and_privileges(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        assert service.get("cap_drop") == ["ALL"], f"{name}: cap_drop ALL required"
        assert "no-new-privileges:true" in service.get("security_opt", []), name


def test_tls_key_is_mounted_as_a_file_secret(compose: dict[str, Any]) -> None:
    gateway = _services(compose)["gateway"]
    assert {"tls_cert", "tls_key"} <= set(gateway["secrets"])
    for volume in gateway.get("volumes", []):
        assert "certs" not in str(volume), "mount TLS files as secrets, not a directory"
    for name in ("tls_cert", "tls_key"):
        assert compose["secrets"][name]["file"].startswith("${EASYAUDIT_CERTS_DIR:-./certs}/")
    assert "/run/secrets/tls_key" in (COMPOSE_PATH.parent / "Caddyfile").read_text()


def test_dockerfiles_drop_root() -> None:
    for dockerfile in (
        ROOT / "Dockerfile",
        ROOT / "web" / "Dockerfile",
        ROOT / "deploy" / "object-storage" / "Dockerfile",
    ):
        users = re.findall(r"^\s*USER\s+(\S+)", dockerfile.read_text(), re.MULTILINE)
        assert users, f"{dockerfile} has no USER"
        assert users[-1].split(":")[0] not in {"0", "root"}, dockerfile


def test_no_inline_plaintext_secrets(compose: dict[str, Any]) -> None:
    for name, service in _services(compose).items():
        environment = service.get("environment", {})
        if isinstance(environment, list):
            environment = dict(item.split("=", 1) for item in environment)
        for key, value in environment.items():
            if SECRET_KEY.search(key):
                assert key.endswith("_FILE"), f"{name}: {key} must use a *_FILE secret"
            assert not re.search(r"://[^/\s:@]+:[^/\s@]+@", str(value)), f"{name}: {key} has creds"
    for secret in compose["secrets"].values():
        assert "file" in secret and "environment" not in secret
        assert secret["file"].startswith(
            ("${EASYAUDIT_SECRETS_DIR:-./secrets}/", "${EASYAUDIT_CERTS_DIR:-./certs}/")
        )


def test_api_trusts_only_the_gateway_for_proxy_headers(compose: dict[str, Any]) -> None:
    services = _services(compose)
    allowed = services["api"]["environment"]["FORWARDED_ALLOW_IPS"]
    gateway_ip = services["gateway"]["networks"]["edge"]["ipv4_address"]
    assert allowed == gateway_ip
    assert "*" not in allowed


def test_api_does_not_migrate_on_startup(compose: dict[str, Any]) -> None:
    api = _services(compose)["api"]
    assert "alembic" not in str(api.get("command", ""))
    assert _services(compose)["migrate"]["command"][:2] == ["alembic", "upgrade"]
    assert "migrate" in _services(compose)["migrate"]["profiles"]


def test_operator_scripts_parse() -> None:
    scripts = sorted([*(ROOT / "deploy").glob("*.sh"), *(ROOT / "deploy" / "backup").glob("*.sh")])
    assert {path.name for path in scripts} >= {"backup.sh", "restore.sh", "verify.sh", "drill.sh"}
    for script in scripts:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, f"{script}: {result.stderr}"


def test_restore_checks_emptiness_before_writing() -> None:
    text = (ROOT / "deploy" / "backup" / "restore.sh").read_text()
    assert text.index("require_empty_database") < text.index("db_tool pg_restore")
    assert text.index("require_empty_bucket") < text.index("copy /data")
    # A whole-environment restore checks both targets before either is written.
    environment = text[text.index("restore_environment() {") :]
    checks = [
        environment.index("require_empty_database"),
        environment.index("require_empty_bucket"),
    ]
    assert max(checks) < environment.index("  restore_database\n")


def test_every_restore_entry_point_checks_the_release_first() -> None:
    text = (ROOT / "deploy" / "backup" / "restore.sh").read_text()
    dispatch = text[text.index('case "$COMMAND" in') :]
    assert 'database) require_release_match "$BACKUP"' in dispatch
    assert 'objects) require_release_match "$BACKUP"' in dispatch
    assert 'require_release_match "$BACKUP"' in text[text.index("restore_environment() {") :]


def test_backup_timer_keeps_snapshots_well_inside_24_hours() -> None:
    timer = (ROOT / "deploy" / "backup" / "easyaudit-backup.timer").read_text()
    assert "RandomizedDelaySec" not in timer
    calendar = re.search(r"^OnCalendar=.* (\d\d),(\d\d):\d\d:\d\d$", timer, re.MULTILINE)
    assert calendar is not None, "expected two runs per day"
    first, second = int(calendar.group(1)), int(calendar.group(2))
    assert max(second - first, 24 - (second - first)) <= 12
