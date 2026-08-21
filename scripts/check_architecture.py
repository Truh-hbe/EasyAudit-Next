import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "easyaudit_next"
SCENARIO_ROOT = SOURCE_ROOT / "scenarios"
COMPOSITION_ROOT = SOURCE_ROOT / "composition.py"
DOMAIN_DIRECTORIES = (
    SOURCE_ROOT / "platform" / "domain",
    SOURCE_ROOT / "review_core" / "domain",
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


def imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


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
        if path.is_relative_to(SCENARIO_ROOT) or path == COMPOSITION_ROOT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported_modules(tree):
            if module.startswith(SCENARIO_IMPORT_PREFIX):
                raise SystemExit(
                    "Scenario modules may only be imported by the composition root: "
                    f"{path}: {module}"
                )

    print(
        "Architecture check passed "
        f"({len(domain_files)} domain/scenario files; Scenario imports are composition-only)."
    )


if __name__ == "__main__":
    main()
