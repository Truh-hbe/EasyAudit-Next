"""Container entry point: uvicorn with JSON logs and no built-in access log."""

import uvicorn

from easyaudit_next.infrastructure.observability import build_log_config
from easyaudit_next.platform.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "easyaudit_next.main:app",
        host=settings.app_host,
        port=settings.app_port,
        log_config=build_log_config(settings.log_level),
        access_log=False,
    )


if __name__ == "__main__":
    main()
