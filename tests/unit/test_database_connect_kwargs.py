from easyaudit_next.infrastructure.database import libpq_connect_kwargs


def test_plain_url_keeps_target_and_credentials() -> None:
    kwargs = libpq_connect_kwargs("postgresql+psycopg://u:p%40w@db.example:5433/app")

    assert kwargs == {
        "host": "db.example",
        "port": 5433,
        "user": "u",
        "password": "p@w",
        "dbname": "app",
    }


def test_url_query_parameters_reach_libpq_unchanged() -> None:
    kwargs = libpq_connect_kwargs(
        "postgresql+psycopg://u:p@db.example/app"
        "?sslmode=verify-full&sslrootcert=/ca.pem&options=-c%20search_path%3Dx"
    )

    assert kwargs["sslmode"] == "verify-full"
    assert kwargs["sslrootcert"] == "/ca.pem"
    assert kwargs["options"] == "-c search_path=x"


def test_unix_socket_host_is_preserved() -> None:
    kwargs = libpq_connect_kwargs("postgresql+psycopg://u:p@/app?host=/var/run/postgresql")

    assert kwargs["host"] == "/var/run/postgresql"


def test_probe_limits_are_added_and_options_are_merged_not_replaced() -> None:
    kwargs = libpq_connect_kwargs(
        "postgresql+psycopg://u:p@db/app?options=-c%20search_path%3Dx&connect_timeout=30",
        connect_timeout=2,
        statement_timeout_ms=2000,
    )

    assert kwargs["connect_timeout"] == 2
    assert kwargs["options"] == "-c search_path=x -c statement_timeout=2000"


def test_options_are_just_the_limit_when_url_has_none() -> None:
    kwargs = libpq_connect_kwargs("postgresql+psycopg://u:p@db/app", statement_timeout_ms=1500)

    assert kwargs["options"] == "-c statement_timeout=1500"


def test_business_engine_gets_client_side_limits_and_merged_options() -> None:
    from easyaudit_next.infrastructure.database import business_connect_args
    from easyaudit_next.platform.settings import Settings

    args = business_connect_args(
        Settings(
            database_url="postgresql+psycopg://u:p@db/app?options=-c%20search_path%3Dx",
            db_connect_timeout_seconds=4,
            db_tcp_user_timeout_ms=9000,
        )
    )

    assert args["options"].startswith("-c search_path=x -c statement_timeout=")
    assert args["connect_timeout"] == 4
    assert args["tcp_user_timeout"] == 9000
    assert args["keepalives"] == 1
    assert {"keepalives_idle", "keepalives_interval", "keepalives_count"} <= set(args)


def test_url_parameters_are_not_overridden_by_client_limits() -> None:
    from easyaudit_next.infrastructure.database import business_connect_args
    from easyaudit_next.platform.settings import Settings

    args = business_connect_args(
        Settings(
            database_url="postgresql+psycopg://u:p@db/app?connect_timeout=30&keepalives_idle=77"
        )
    )

    assert "connect_timeout" not in args  # the URL's own value reaches libpq unchanged
    assert "keepalives_idle" not in args
    assert args["tcp_user_timeout"] == 15000


def test_pool_must_allow_two_connections() -> None:
    import pytest

    from easyaudit_next.platform.settings import Settings

    with pytest.raises(ValueError, match="at least 2"):
        Settings(db_pool_size=1, db_max_overflow=0)
    assert Settings(db_pool_size=1, db_max_overflow=1).db_pool_size == 1
