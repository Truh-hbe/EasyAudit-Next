"""The web process never hosts the reminder scheduler: it runs as a systemd timer + CLI."""

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_architecture", ROOT / "scripts" / "check_architecture.py"
)
WEB_FILE = ROOT / "src" / "easyaudit_next" / "api" / "x.py"
assert _spec and _spec.loader
check_architecture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_architecture)


@pytest.mark.parametrize(
    "source",
    [
        "from easyaudit_next.collaboration.reminder_sweep import AutomaticReminderSweep",
        "import easyaudit_next.collaboration.scheduler_runs",
        "from easyaudit_next.cli import main",
        "from easyaudit_next.composition import build_per_candidate_reminder_sweep",
        "from easyaudit_next.composition import build_automatic_reminder_sweep",
        "import apscheduler.schedulers.background",
        "from sched import scheduler",
        # aliases and package members
        "from easyaudit_next import composition\ncomposition.build_per_candidate_reminder_sweep",
        "from easyaudit_next import composition as c\nc.build_automatic_reminder_sweep(None)",
        "import easyaudit_next.composition as c\nc.build_per_candidate_reminder_sweep",
        "import easyaudit_next.composition\n"
        "easyaudit_next.composition.build_per_candidate_reminder_sweep",
        "from easyaudit_next.collaboration import reminder_sweep",
        "from easyaudit_next.collaboration import scheduler_runs as runs",
        "from easyaudit_next import cli",
        # relative imports (WEB_FILE is easyaudit_next/api/x.py)
        "from .. import composition\ncomposition.build_per_candidate_reminder_sweep",
        "from ..composition import build_per_candidate_reminder_sweep",
        "from ..collaboration import reminder_sweep",
        "from ..collaboration.reminder_sweep import AutomaticReminderSweep",
        "from .. import cli",
    ],
)
def test_checker_rejects_scheduler_in_web_process(source: str) -> None:
    with pytest.raises(SystemExit):
        check_architecture.check_web_process_has_no_scheduler(WEB_FILE, ast.parse(source))


def test_checker_allows_ordinary_composition_imports() -> None:
    check_architecture.check_web_process_has_no_scheduler(
        WEB_FILE,
        ast.parse("from easyaudit_next.composition import build_notification_service"),
    )


def test_web_process_files_are_covered_by_the_rule() -> None:
    source_root = ROOT / "src" / "easyaudit_next"
    for path in (
        source_root / "main.py",
        source_root / "serve.py",
        source_root / "api" / "router.py",
        source_root / "collaboration" / "api.py",
        source_root / "notifications" / "api.py",
    ):
        assert check_architecture.is_web_process_file(path), path
    assert not check_architecture.is_web_process_file(source_root / "cli.py")


def test_checker_allows_composition_module_alias_for_other_builders() -> None:
    check_architecture.check_web_process_has_no_scheduler(
        WEB_FILE,
        ast.parse(
            "from easyaudit_next import composition\n"
            "composition.build_notification_service\n"
            "from ..collaboration import api\n"
        ),
    )


def test_cli_may_use_the_sweep_and_the_whole_repository_passes() -> None:
    cli_path = ROOT / "src" / "easyaudit_next" / "cli.py"
    assert not check_architecture.is_web_process_file(cli_path)
    tree = ast.parse(cli_path.read_text(encoding="utf-8"))
    names, _ = check_architecture.resolve_imports(tree, cli_path)
    assert "easyaudit_next.composition.build_per_candidate_reminder_sweep" in names
    check_architecture.main()
