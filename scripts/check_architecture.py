import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "easyaudit_next"
SCENARIO_ROOT = SOURCE_ROOT / "scenarios"
REVIEW_CORE_ROOT = SOURCE_ROOT / "review_core"
COLLABORATION_ROOT = SOURCE_ROOT / "collaboration"
COMPOSITION_ROOT = SOURCE_ROOT / "composition.py"
DOMAIN_DIRECTORIES = (
    SOURCE_ROOT / "platform" / "domain",
    REVIEW_CORE_ROOT / "domain",
    SCENARIO_ROOT,
)
FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "alembic",
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "easyaudit_next.api",
    "easyaudit_next.infrastructure",
    "easyaudit_next.platform.application",
    "easyaudit_next.review_core.application",
    "easyaudit_next.review_core.persistence",
)
SCENARIO_IMPORT_PREFIX = "easyaudit_next.scenarios"
DOWNSTREAM_IMPORT_PREFIXES = (
    "easyaudit_next.collaboration",
    "easyaudit_next.management",
    "easyaudit_next.notifications",
    "easyaudit_next.workbench",
)
OBSERVABILITY_IMPORT_PREFIXES = (
    "easyaudit_next.infrastructure.observability",
    "easyaudit_next.infrastructure.readiness",
)
OBSERVABILITY_CONSUMERS = (
    SOURCE_ROOT / "api",
    SOURCE_ROOT / "infrastructure",
    SOURCE_ROOT / "main.py",
    SOURCE_ROOT / "serve.py",
)
INFRASTRUCTURE_ROOT = SOURCE_ROOT / "infrastructure"
OBJECT_STORAGE_SDK_PREFIXES = ("boto3", "botocore", "aioboto3", "aiobotocore", "minio")
OBJECT_STORAGE_ADAPTER = "easyaudit_next.infrastructure.object_storage"
# Scheduling lives outside the web process (systemd timer -> `easyaudit-next run-reminder-sweep`).
# The HTTP edge must not import the sweep, the run records, the CLI, or a scheduler library.
WEB_PROCESS_PATHS = (SOURCE_ROOT / "api", SOURCE_ROOT / "main.py", SOURCE_ROOT / "serve.py")
FORBIDDEN_WEB_IMPORT_PREFIXES = (
    "easyaudit_next.collaboration.reminder_sweep",
    "easyaudit_next.collaboration.scheduler_runs",
    "easyaudit_next.collaboration.automatic_reminder",
    "easyaudit_next.cli",
)
FORBIDDEN_WEB_THIRD_PARTY = {"apscheduler", "celery", "schedule", "sched", "rq"}
FORBIDDEN_WEB_COMPOSITION_NAMES = {
    "build_automatic_reminder_sweep",
    "build_per_candidate_reminder_sweep",
    "build_automatic_reminder_evaluator",
}
FORBIDDEN_GENERIC_RECIPIENT_PERMISSION_LITERALS = {
    "submit_rectification",
    "update_assigned_action",
    "transition_case",
}
# Credential rows are leaf rows (nothing references them), so FOR UPDATE is harmless there.
FOR_UPDATE_ALLOWED_FUNCTIONS = {
    (SOURCE_ROOT / "platform" / "persistence" / "repositories.py", "lock_by_login_name"),
    (SOURCE_ROOT / "platform" / "persistence" / "repositories.py", "lock_by_user_id"),
}


def imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def imports_name(tree: ast.AST, module: str, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            if any(alias.name == name for alias in node.names):
                return True
    return False


def keyword_is_true(call: ast.Call, name: str) -> bool:
    return any(
        keyword.arg == name
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )


def parent_lock_violations(path: Path, tree: ast.AST) -> list[str]:
    """Row locks must be FOR NO KEY UPDATE: `key_share=True` without `read=True`."""

    violations: list[str] = []

    def visit(node: ast.AST, function: str | None) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "with_for_update"
            and (path, function) not in FOR_UPDATE_ALLOWED_FUNCTIONS
            and not (keyword_is_true(node, "key_share") and not keyword_is_true(node, "read"))
        ):
            violations.append(f"{path}:{node.lineno}")
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, None)
    return violations


def string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def is_web_process_file(path: Path) -> bool:
    # Any HTTP adapter: src/.../api/**, per-module api.py routers, main.py, serve.py.
    return path.name == "api.py" or any(
        path == allowed or path.is_relative_to(allowed) for allowed in WEB_PROCESS_PATHS
    )


COMPOSITION_MODULE = "easyaudit_next.composition"


def _current_package(path: Path) -> list[str]:
    relative = path.resolve().relative_to(SOURCE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    return parts if path.name == "__init__.py" else parts[:-1]


def resolve_imports(tree: ast.AST, path: Path) -> tuple[list[str], dict[str, str]]:
    """Absolute dotted names every import statement can bring in, plus the local alias map.

    Relative imports are resolved against `path`; `from pkg import name` yields both `pkg` and
    `pkg.name`, because `name` may itself be a module.
    """
    names: list[str] = []
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _current_package(path)
                base_parts = package[: len(package) - (node.level - 1)]
                base = ".".join([*base_parts, *(node.module.split(".") if node.module else [])])
            else:
                base = node.module or ""
            if base:
                names.append(base)
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                names.append(full)
                aliases[alias.asname or alias.name] = full
    return names, aliases


def _dotted(node: ast.AST, aliases: dict[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(aliases.get(node.id, node.id))
    return ".".join(reversed(parts))


def _is_forbidden_web_name(name: str) -> bool:
    return any(
        name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_WEB_IMPORT_PREFIXES
    ) or name.split(".")[0] in FORBIDDEN_WEB_THIRD_PARTY


def check_web_process_has_no_scheduler(path: Path, tree: ast.AST) -> None:
    names, aliases = resolve_imports(tree, path)
    for name in names:
        if _is_forbidden_web_name(name):
            raise SystemExit(
                f"Web process must not host a scheduler or sweep (use the CLI): {path}: {name}"
            )
        module, _, member = name.rpartition(".")
        if module == COMPOSITION_MODULE and member in FORBIDDEN_WEB_COMPOSITION_NAMES:
            raise SystemExit(f"Web process must not wire the reminder sweep: {path}: {name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_WEB_COMPOSITION_NAMES:
            owner = _dotted(node.value, aliases)
            if owner == COMPOSITION_MODULE:
                raise SystemExit(
                    f"Web process must not wire the reminder sweep: {path}: {owner}.{node.attr}"
                )


def main() -> None:
    domain_files = sorted(
        path for directory in DOMAIN_DIRECTORIES for path in directory.rglob("*.py")
    )
    if not domain_files:
        raise SystemExit("No domain files found")

    for path in domain_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported_modules(tree):
            if module.startswith(FORBIDDEN_DOMAIN_IMPORT_PREFIXES):
                raise SystemExit(
                    f"Domain layer imports infrastructure/application: {path}: {module}"
                )

    source_files = sorted(SOURCE_ROOT.rglob("*.py"))
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported_modules(tree):
            if (
                not path.is_relative_to(SCENARIO_ROOT)
                and path != COMPOSITION_ROOT
                and module.startswith(SCENARIO_IMPORT_PREFIX)
            ):
                raise SystemExit(
                    "Scenario modules may only be imported by the composition root: "
                    f"{path}: {module}"
                )
            if module.startswith(OBSERVABILITY_IMPORT_PREFIXES) and not any(
                path == allowed or path.is_relative_to(allowed)
                for allowed in OBSERVABILITY_CONSUMERS
            ):
                raise SystemExit(
                    "Observability/readiness infrastructure may only be used by the API edge: "
                    f"{path}: {module}"
                )
            if module.split(".")[0] in OBJECT_STORAGE_SDK_PREFIXES and not path.is_relative_to(
                INFRASTRUCTURE_ROOT
            ):
                raise SystemExit(
                    "Object storage SDKs may only be imported by infrastructure adapters; "
                    f"business code depends on the EvidenceObjectStore port: {path}: {module}"
                )
            if module.startswith(OBJECT_STORAGE_ADAPTER) and not (
                path.is_relative_to(INFRASTRUCTURE_ROOT) or path == COMPOSITION_ROOT
            ):
                raise SystemExit(
                    "The object storage adapter may only be wired by the composition root: "
                    f"{path}: {module}"
                )
            if path.is_relative_to(REVIEW_CORE_ROOT) and module.startswith(
                DOWNSTREAM_IMPORT_PREFIXES
            ):
                raise SystemExit(
                    "Review Core must not depend on collaboration/read-side modules: "
                    f"{path}: {module}"
                )

        if is_web_process_file(path):
            check_web_process_has_no_scheduler(path, tree)

        violations = parent_lock_violations(path, tree)
        if violations:
            raise SystemExit(
                "Row locks must use with_for_update(key_share=True) (FOR NO KEY UPDATE); "
                f"FOR UPDATE conflicts with FK FOR KEY SHARE: {violations}"
            )

        if path.is_relative_to(COLLABORATION_ROOT) and imports_name(
            tree,
            "easyaudit_next.review_core.persistence.models",
            "ActivityRecord",
        ):
            raise SystemExit(
                "Collaboration orchestration must consume exact ActivityId output, "
                f"not query ActivityRecord: {path}"
            )

        if path.is_relative_to(COLLABORATION_ROOT):
            coupled = string_literals(tree).intersection(
                FORBIDDEN_GENERIC_RECIPIENT_PERMISSION_LITERALS
            )
            if coupled:
                raise SystemExit(
                    "Generic collaboration code must use Scenario recipient intents rather than "
                    f"recipient permission coupling: {path}: {sorted(coupled)}"
                )

    print(
        "Architecture check passed "
        f"({len(domain_files)} domain/scenario files; Scenario imports are composition-only; "
        "Review Core is downstream-independent; Notification provenance is propagated; "
        "recipient responsibility remains Scenario-owned)."
    )


if __name__ == "__main__":
    main()
