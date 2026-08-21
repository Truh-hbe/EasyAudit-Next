import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAIN_DIRECTORIES = (
    ROOT / "src" / "easyaudit_next" / "platform" / "domain",
    ROOT / "src" / "easyaudit_next" / "review_core" / "domain",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "alembic",
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "easyaudit_next.api",
    "easyaudit_next.infrastructure",
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
    files = sorted(path for directory in DOMAIN_DIRECTORIES for path in directory.glob("*.py"))
    if not files:
        raise SystemExit("No domain files found")

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported_modules(tree):
            if module.startswith(FORBIDDEN_IMPORT_PREFIXES):
                raise SystemExit(f"Domain layer imports infrastructure: {path}: {module}")

    print(f"Architecture check passed ({len(files)} domain files across platform and review core).")


if __name__ == "__main__":
    main()
