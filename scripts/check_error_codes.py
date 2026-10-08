"""Guard the structured error-code contract (docs/architecture.md, "API 错误语义").

1. Business code that can surface as a 422 must raise `RuleViolation` (which requires a code),
   never a bare `ValueError` or a `ValueError` subclass without a code.
2. Every `RuleCode` is referenced by production code, so no code is declared and forgotten.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "easyaudit_next"
RULES_MODULE = SOURCE_ROOT / "rules.py"

# Packages whose ValueErrors reach the API as 422.
GUARDED = (
    SOURCE_ROOT / "review_core" / "application",
    SOURCE_ROOT / "scenarios",
    SOURCE_ROOT / "review_resource_queries",
    SOURCE_ROOT / "review_case_queries",
    SOURCE_ROOT / "management",
    SOURCE_ROOT / "workbench",
    SOURCE_ROOT / "collaboration" / "nudge.py",
    SOURCE_ROOT / "platform" / "application" / "password_policy.py",
)
# Start-up configuration and catalog publishing: never answered as a request validation error.
ALLOWED = {
    SOURCE_ROOT / "review_core" / "application" / "evidence_policy.py": {"ValueError"},
    SOURCE_ROOT / "review_core" / "application" / "scenario_catalog.py": {
        "ScenarioVersionAlreadyPublishedError"
    },
}


def guarded_files() -> list[Path]:
    files: list[Path] = []
    for entry in GUARDED:
        files.extend(sorted(entry.rglob("*.py")) if entry.is_dir() else [entry])
    return files


def name_of(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def uncoded_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed = ALLOWED.get(path, set())
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            if name_of(node.exc) == "ValueError" and "ValueError" not in allowed:
                problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: raise ValueError")
        if isinstance(node, ast.ClassDef) and node.name not in allowed:
            if any(name_of(base) == "ValueError" for base in node.bases):
                problems.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: {node.name} subclasses ValueError; "
                    "subclass RuleViolation"
                )
    return problems


def declared_codes() -> list[str]:
    tree = ast.parse(RULES_MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "RuleCode":
            return [
                target.id
                for statement in node.body
                if isinstance(statement, ast.Assign)
                for target in statement.targets
                if isinstance(target, ast.Name)
            ]
    raise SystemExit("RuleCode not found in rules.py")


def referenced_codes() -> set[str]:
    used: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        if path == RULES_MODULE:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "RuleCode"
            ):
                used.add(node.attr)
    return used


def main() -> None:
    problems = [problem for path in guarded_files() for problem in uncoded_violations(path)]
    if problems:
        raise SystemExit("Rule violations without a code:\n" + "\n".join(problems))

    declared = declared_codes()
    unused = sorted(set(declared) - referenced_codes())
    if unused:
        raise SystemExit(f"RuleCode members never raised or mapped: {unused}")

    print(f"Error code check passed ({len(declared)} rule codes, all referenced).")


if __name__ == "__main__":
    main()
