import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIRECTORIES = (
    ROOT / "src" / "easyaudit_next" / "platform" / "domain",
    ROOT / "src" / "easyaudit_next" / "review_core" / "domain",
    ROOT / "src" / "easyaudit_next" / "scenarios",
)
FORBIDDEN_IMPORT_PREFIXES = (
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


def imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def main() -> None:
    files = sorted(
        path for directory in DOMAIN_DIRECTORIES for path in directory.rglob("*.py")
    )
    if not files:
        raise SystemExit("No domain files found")

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported_modules(tree):
            if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                raise SystemExit(f"Domain layer imports infrastructure/application: {path}: {module}")

    print(
        "Architecture check passed "
        f"({len(files)} domain/scenario files across platform, review core, and scenarios)."
    )


if __name__ == "__main__":
    main()
