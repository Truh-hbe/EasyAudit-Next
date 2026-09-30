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
