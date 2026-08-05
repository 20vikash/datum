"""Setup is the only thing that writes config, so what it emits matters."""

import pytest

from datum.config.vmauth import PUBLIC_KEY_FILE_VARIABLE
from datum.setup import Installer, Options


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "central.pub"
    path.write_text("-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n")
    return path


def installer(*argv) -> Installer:
    return Installer(Options.from_argv(["--dry-run", *argv]))


def units(*argv) -> dict[str, str]:
    return installer(*argv).units(required=False)


def test_the_api_unit_carries_the_store_and_the_key(key):
    unit = units("--public-key", str(key))["datum-api"]

    assert "Environment=DATUM_URL=http://127.0.0.1:8428\n" in unit
    assert f"Environment={PUBLIC_KEY_FILE_VARIABLE}={key.resolve()}\n" in unit


def test_no_unit_reads_an_env_file(key):
    assert not any("EnvironmentFile" in unit for unit in units("--public-key", str(key)).values())


def test_oidc_reaches_the_api_unit_too():
    """One flag configures both sides, or the read path silently 401s."""
    built = units("--oidc-issuer", "https://central.frappe.io")

    assert "Environment=DATUM_OIDC_ISSUER=https://central.frappe.io\n" in built["datum-api"]
    assert 'issuer: "https://central.frappe.io"' not in built["datum-api"]


def test_skip_verify_leaves_reads_closed():
    """Writes open and reads shut is deliberate for a local testing mode."""
    unit = units("--skip-verify")["datum-api"]

    assert PUBLIC_KEY_FILE_VARIABLE not in unit
    assert "DATUM_OIDC_ISSUER" not in unit


def test_a_missing_key_file_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(RuntimeError, match="is not a file"):
        units("--public-key", str(tmp_path / "absent.pem"))


def test_picking_two_modes_is_refused(key):
    with pytest.raises(RuntimeError, match="accepts one"):
        units("--public-key", str(key), "--oidc-issuer", "https://central.frappe.io")


def test_the_listen_address_reaches_the_vmauth_unit(key):
    built = installer("--public-key", str(key), "--vmauth-listen", "0.0.0.0:9427")

    assert "-httpListenAddr=0.0.0.0:9427" in built.units(required=False)["vmauth"]
    assert built.vmauth.listen == "0.0.0.0:9427"


def test_the_config_dir_is_where_vmauth_looks(key, tmp_path):
    built = units("--public-key", str(key), "--config-dir", str(tmp_path))

    assert f"-auth.config={tmp_path / 'vmauth.yml'}" in built["vmauth"]


def test_the_store_address_reaches_both_units(key):
    """One flag moves VictoriaMetrics and what the API is told to call."""
    built = units("--public-key", str(key), "--victoria-listen", "127.0.0.1:9428")

    assert "-httpListenAddr=127.0.0.1:9428" in built["victoria-metrics"]
    assert "Environment=DATUM_URL=http://127.0.0.1:9428\n" in built["datum-api"]


def test_the_store_address_reaches_vmauth(key):
    built = installer("--public-key", str(key), "--victoria-listen", "127.0.0.1:9428")

    assert built.vmauth.victoria_url == "http://127.0.0.1:9428"


def test_retention_and_memory_are_not_hardcoded_in_the_unit(key):
    built = units("--public-key", str(key), "--retention", "3", "--memory-percent", "25")

    assert "-retentionPeriod=3" in built["victoria-metrics"]
    assert "-memory.allowedPercent=25" in built["victoria-metrics"]


def test_config_only_writes_the_config_and_no_units(key, tmp_path):
    """The Mac path: config, and nothing systemd would need."""
    options = Options.from_argv(
        ["--config-only", "--public-key", str(key), "--config-dir", str(tmp_path)]
    )
    Installer(options).write_config()

    assert (tmp_path / "vmauth.yml").is_file()
    assert not list(tmp_path.glob("*.service"))


def test_the_config_is_written_private(key, tmp_path):
    options = Options.from_argv(
        ["--config-only", "--public-key", str(key), "--config-dir", str(tmp_path)]
    )
    Installer(options).write_config()

    assert (tmp_path / "vmauth.yml").stat().st_mode & 0o077 == 0


def test_rewriting_identical_config_reports_no_change(key, tmp_path):
    """A repeat run must restart nothing."""
    options = Options.from_argv(
        ["--config-only", "--public-key", str(key), "--config-dir", str(tmp_path)]
    )
    assert Installer(options).write_config() is True
    assert Installer(options).write_config() is False


def test_the_scope_flag_reaches_the_vmauth_config(key):
    built = installer("--public-key", str(key), "--scope", "metrics")

    assert '      scope: "metrics"\n' in built.config


def test_the_scope_defaults_to_datum(key):
    assert '      scope: "datum"\n' in installer("--public-key", str(key)).config


def test_an_empty_scope_drops_the_match(key):
    """Every token the key signed may then write, which is rarely what you want."""
    assert "match_claims" not in installer("--public-key", str(key), "--scope", "").config
