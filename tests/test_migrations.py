import pytest

from datum.migrations import migrations

PASSWORDS = {"DATUM_PASSWORD": "pw-datum", "INSIGHTS_PASSWORD": "pw-insights"}


class FakeClient:
    def __init__(self):
        self.commands: list[str] = []
        self.options: dict = {}

    def command(self, statement):
        self.commands.append(statement)


@pytest.fixture
def client(monkeypatch):
    fake = FakeClient()

    def connect(**options):
        fake.options = options
        return fake

    monkeypatch.setattr(migrations.clickhouse_connect, "get_client", connect)
    return fake


@pytest.fixture(autouse=True)
def no_ambient_passwords(monkeypatch):
    """A developer's own env must not decide what a test asserts."""
    for variable in ("DATUM_CLICKHOUSE_PASSWORD", "INSIGHTS_PASSWORD"):
        monkeypatch.delenv(variable, raising=False)


def test_migrations_run_in_name_order():
    """The numeric prefix is the ordering: ACL before the tables that reference it."""
    names = [path.name for path in migrations.get_migrations()]

    assert names == sorted(names)
    assert names[0].startswith("000")


def test_comments_are_dropped_before_splitting():
    sql = "SELECT 1; -- a comment; with a semicolon\nSELECT 2;"

    assert migrations.get_statements(sql) == ["SELECT 1", "SELECT 2"]


def test_a_trailing_statement_without_a_semicolon_still_counts():
    assert migrations.get_statements("SELECT 1") == ["SELECT 1"]


def test_a_comment_only_file_yields_nothing():
    assert migrations.get_statements("-- nothing here\n\n") == []


def test_every_placeholder_is_filled(client):
    """A leftover `${...}` would reach ClickHouse as a literal password."""
    migrations.run_migrations(host="h", port=8123, username="d", password="", **PASSWORDS)

    assert not any("${" in command for command in client.commands)


def test_both_users_are_created_with_the_passwords_given(client):
    migrations.run_migrations(host="h", port=8123, username="d", password="", **PASSWORDS)
    created = [c for c in client.commands if c.startswith("CREATE USER")]

    assert "IDENTIFIED BY 'pw-datum'" in created[0]
    assert "IDENTIFIED BY 'pw-insights'" in created[1]


def test_datum_is_granted_no_ddl(client):
    """Migrations make the schema; the service only writes rows."""
    migrations.run_migrations(host="h", port=8123, username="d", password="", **PASSWORDS)
    granted = next(
        c for c in client.commands if c.startswith("GRANT") and "TO datum" in c
    )

    assert "CREATE" not in granted
    assert "INSERT" in granted


def test_running_applies_every_file(client):
    ran = migrations.run_migrations(host="localhost", port=8123, username="d", password="", **PASSWORDS)

    assert ran == [path.name for path in migrations.get_migrations()]
    assert any("CREATE TABLE IF NOT EXISTS datum.samples" in c for c in client.commands)


def test_the_acl_runs_before_the_tables(client):
    migrations.run_migrations(host="localhost", port=8123, username="d", password="", **PASSWORDS)
    commands = client.commands

    first_user = next(i for i, c in enumerate(commands) if c.startswith("CREATE USER"))
    first_table = next(i for i, c in enumerate(commands) if "CREATE TABLE" in c)
    assert first_user < first_table


def test_the_insights_password_is_required(monkeypatch, capsys):
    """It is stored nowhere, so there is nothing to fall back to."""
    monkeypatch.setattr("sys.argv", ["datum-migrate"])

    with pytest.raises(SystemExit):
        migrations.main()

    assert "--insights-user-password" in capsys.readouterr().err


def test_an_unfilled_placeholder_is_an_error_not_a_password(client):
    """safe_substitute would leave `${INSIGHTS_PASSWORD}` as the literal password."""
    with pytest.raises(KeyError):
        migrations.run_migrations(
            host="localhost", port=8123, username="default", password="",
            DATUM_PASSWORD="pw-datum",
        )


def test_connection_and_passwords_come_from_the_env_file(monkeypatch, client):
    monkeypatch.setattr("sys.argv", ["datum-migrate", "--insights-user-password", "typed"])
    monkeypatch.setenv("DATUM_CLICKHOUSE_HOST", "clickhouse.local")
    monkeypatch.setenv("DATUM_CLICKHOUSE_PASSWORD", "from-env")

    migrations.main()

    assert client.options["host"] == "clickhouse.local"
    assert any("IDENTIFIED BY 'from-env'" in c for c in client.commands)
    assert any("IDENTIFIED BY 'typed'" in c for c in client.commands)


def test_a_missing_host_fails_before_connecting(monkeypatch):
    monkeypatch.setattr("sys.argv", ["datum-migrate", "--insights-user-password", "typed"])
    monkeypatch.delenv("DATUM_CLICKHOUSE_HOST", raising=False)

    with pytest.raises(SystemExit, match="DATUM_CLICKHOUSE_HOST"):
        migrations.main()
