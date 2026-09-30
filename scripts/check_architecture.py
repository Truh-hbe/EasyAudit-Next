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
FORBIDDEN_GENERIC_RECIPIENT_PERMISSION_LITERALS = {
    "submit_rectification",
    "update_assigned_action",
    "transition_case",
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


def string_literals(tree: ast.AST) -> set[str]:
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


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
            if path.is_relative_to(REVIEW_CORE_ROOT) and module.startswith(
                DOWNSTREAM_IMPORT_PREFIXES
            ):
                raise SystemExit(
                    "Review Core must not depend on collaboration/read-side modules: "
                    f"{path}: {module}"
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
