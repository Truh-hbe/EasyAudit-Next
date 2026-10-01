from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def test_sweep_timer_is_daily_nine_shanghai_and_service_runs_the_cli() -> None:
    timer = (DEPLOY / "easyaudit-reminder-sweep.timer").read_text()
    service = (DEPLOY / "easyaudit-reminder-sweep.service").read_text()
    assert "OnCalendar=*-*-* 09:00:00 Asia/Shanghai" in timer
    assert "easyaudit-next run-reminder-sweep" in service
    assert "run --rm --no-deps -T api" in service
    assert "Type=oneshot" in service


def test_status_service_checks_26_hours() -> None:
    service = (DEPLOY / "easyaudit-reminder-status.service").read_text()
    assert "easyaudit-next scheduler-status --max-age-hours 26" in service
