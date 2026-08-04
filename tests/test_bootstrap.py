"""bootstrap.py is the only thing that writes config, so what it emits matters."""

import pytest

import bootstrap
from datum.api.internals.auth import PUBLIC_KEY_FILE_VARIABLE


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "central.pub"
    path.write_text("-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n")
    return path


def units(*argv):
    arguments = bootstrap.parse_arguments(["--dry-run", *argv])
    settings = bootstrap.build_vmauth_settings(arguments)
    return bootstrap.build_units(arguments, settings), settings


def test_the_api_unit_carries_the_store_and_the_key(key):
    built, _ = units("--public-key", str(key))

    unit = built["datum-api"]
    assert "Environment=DATUM_URL=http://127.0.0.1:8428\n" in unit
    assert f"Environment={PUBLIC_KEY_FILE_VARIABLE}={key.resolve()}\n" in unit


def test_no_unit_reads_an_env_file(key):
    built, _ = units("--public-key", str(key))

    assert not any("EnvironmentFile" in unit for unit in built.values())


def test_oidc_leaves_the_api_without_a_key(key):
    """Only writes can use OIDC today, and the unit must not pretend otherwise."""
    built, _ = units("--oidc-issuer", "https://central.frappe.io")

    assert PUBLIC_KEY_FILE_VARIABLE not in built["datum-api"]


def test_a_missing_key_file_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(RuntimeError, match="is not a file"):
        units("--public-key", str(tmp_path / "absent.pem"))


def test_picking_two_modes_is_refused(key):
    with pytest.raises(RuntimeError, match="accepts one"):
        units("--public-key", str(key), "--oidc-issuer", "https://central.frappe.io")


def test_the_listen_address_reaches_the_vmauth_unit(key):
    built, settings = units("--public-key", str(key), "--vmauth-listen", "0.0.0.0:9427")

    assert "-httpListenAddr=0.0.0.0:9427" in built["vmauth"]
    assert settings.listen == "0.0.0.0:9427"


def test_the_config_dir_is_where_vmauth_looks(key, tmp_path):
    built, _ = units("--public-key", str(key), "--config-dir", str(tmp_path))

    assert f"-auth.config={tmp_path / 'vmauth.yml'}" in built["vmauth"]
