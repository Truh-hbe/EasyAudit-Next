"""Guard the structured error-code contract (docs/architecture.md, "API 错误语义").

1. Business code that can surface as a 422 must raise `RuleViolation` (which requires a code),
   never a bare `ValueError` or a `ValueError` subclass without a code.
2. Every `RuleCode` is referenced by production code, so no code is declared and forgotten.

Boundary of check 1: it is syntactic. It sees `raise ValueError(...)`, classes that name
`ValueError` as a base, and `raise X(...)` where `X` is, by name, a repository class deriving from
`ValueError` without `RuleViolation` (so imported subclasses are caught). It does not follow
`raise exc` of a variable, factory functions that return exceptions, or exceptions raised by
third-party code. Exceptions that are deliberately not request validation errors are listed in
`ALLOWED` by enclosing function (or class), not by file.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "easyaudit_next"
RULES_MODULE = SOURCE_ROOT / "rules.py"

# Packages whose ValueErrors can reach the API as 422.
GUARDED = (
    SOURCE_ROOT / "review_core" / "application",
    SOURCE_ROOT / "review_core" / "domain",
    SOURCE_ROOT / "scenarios",
    SOURCE_ROOT / "review_resource_queries",
    SOURCE_ROOT / "review_case_queries",
    SOURCE_ROOT / "management",
    SOURCE_ROOT / "workbench",
    SOURCE_ROOT / "collaboration" / "nudge.py",
    SOURCE_ROOT / "platform" / "application" / "password_policy.py",
)

# Programmer/configuration invariants that are never answered as a validation error, keyed by file
# then by the enclosing "Class.function" / "function" / "Class" (for class definitions).
_DOMAIN = SOURCE_ROOT / "review_core" / "domain"
ALLOWED: dict[Path, set[str]] = {
    SOURCE_ROOT / "review_core" / "application" / "evidence_policy.py": {
        "EvidenceUploadPolicy.from_config"  # start-up EVIDENCE_* configuration
    },
    SOURCE_ROOT / "review_core" / "application" / "scenario_catalog.py": {
        "ScenarioVersionAlreadyPublishedError",  # catalog publishing, mapped to 409
        "ScenarioCatalogService.publish",
    },
    _DOMAIN / "models.py": {
        "Scenario.__post_init__",
        "ScenarioDefinition.__post_init__",
        "ScenarioVersionPublication.__post_init__",
    },
    _DOMAIN / "invariants.py": {
        "assert_plan_contains_case",
        "assert_finding_belongs_to_case",
        "assert_unique_finding_participants",
        "assert_unique_action_assignees",
    },
    _DOMAIN / "scenario_capabilities.py": {"RoleSpecification.__post_init__"},
    _DOMAIN / "scenario_registry.py": {"ScenarioRegistry.register"},
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


def uncoded_exception_classes() -> set[str]:
    """Names of repository classes deriving from ValueError but not from RuleViolation."""
    bases: dict[str, set[str]] = {}
    for path in SOURCE_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                bases.setdefault(node.name, set()).update(name_of(base) for base in node.bases)

    def reaches(name: str, target: str, seen: frozenset[str] = frozenset()) -> bool:
        if name == target:
            return True
        if name in seen:
            return False
        return any(reaches(base, target, seen | {name}) for base in bases.get(name, ()))

    return {
        name
        for name in bases
        if reaches(name, "ValueError") and not reaches(name, "RuleViolation")
    }


def scoped_nodes(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    """Every node with its enclosing 'Class.function' scope (class name for a class itself)."""
    found: list[tuple[str, ast.AST]] = []

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                found.append((".".join([*scope, child.name]), child))
                visit(child, [*scope, child.name])
            elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                visit(child, [*scope, child.name])
            else:
                found.append((".".join(scope), child))
                visit(child, scope)

    visit(tree, [])
    return found


def uncoded_violations(path: Path, uncoded: set[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    allowed = ALLOWED.get(path, set())
    problems: list[str] = []
    for scope, node in scoped_nodes(tree):
        if scope in allowed:
            continue
        if isinstance(node, ast.Raise) and node.exc is not None:
            raised = name_of(node.exc)
            if raised == "ValueError" or raised in uncoded:
                problems.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}: raise {raised} without a RuleCode"
                )
        if isinstance(node, ast.ClassDef) and any(name_of(b) == "ValueError" for b in node.bases):
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
    uncoded = uncoded_exception_classes()
    problems = [
        problem for path in guarded_files() for problem in uncoded_violations(path, uncoded)
    ]
    if problems:
        raise SystemExit("Rule violations without a code:\n" + "\n".join(problems))

    declared = declared_codes()
    unused = sorted(set(declared) - referenced_codes())
    if unused:
        raise SystemExit(f"RuleCode members never raised or mapped: {unused}")

    print(f"Error code check passed ({len(declared)} rule codes, all referenced).")


if __name__ == "__main__":
    main()
