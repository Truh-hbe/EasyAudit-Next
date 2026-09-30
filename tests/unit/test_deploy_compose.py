"""Static guardrails for the production topology in deploy/compose.yaml."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "deploy" / "compose.yaml"

# Services allowed to run as root, with the reason. Currently none.
ROOT_EXCEPTIONS: dict[str, str] = {}
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
    name, sep, tag = reference.rpartition(":")
    if not sep or "/" in tag:
        return False
    return bool(tag) and tag != "latest" and not re.fullmatch(r"(latest|stable|alpine|slim)", tag)


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
    assert {"gateway", "web", "api", "postgres", "object-storage", "migrate"} <= set(
        _services(compose)
    )


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
            build = service["build"]
            context = COMPOSE_PATH.parent / build["context"]
            dockerfile = context / build.get("dockerfile", "Dockerfile")
            bases = _dockerfile_bases(dockerfile)
            assert bases, f"{name}: no FROM found in {dockerfile}"
            for base in bases:
                assert _is_pinned(base), f"{name}: {base} in {dockerfile} is not pinned"
        else:
            assert _is_pinned(service["image"]), f"{name}: {service['image']} is not pinned"


def test_data_services_only_on_internal_network(compose: dict[str, Any]) -> None:
    assert compose["networks"]["backend"]["internal"] is True
    assert not compose["networks"]["edge"].get("internal", False)
    services = _services(compose)
    for name in ("postgres", "object-storage", "migrate"):
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
        assert "${EASYAUDIT_SECRETS_DIR:-./secrets}/" in secret["file"]


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
