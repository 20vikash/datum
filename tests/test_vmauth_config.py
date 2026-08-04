"""The vmauth config is the whole write-path security boundary, so its exact
text is asserted rather than its shape."""

import pytest

from datum.vmauth import VmauthSettings, build
from datum.vmauth.settings import ISSUER_VARIABLE, SKIP_VERIFY_VARIABLE
from tests.conftest import PUBLIC_KEY

URL = "http://127.0.0.1:8428"


def settings(**overrides) -> VmauthSettings:
    return VmauthSettings(victoria_url=URL, **overrides)


def test_public_key_config_is_exact():
    written = build(settings(public_key="-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----"))

    assert written == (
        "# Written by bootstrap.py. Edit the environment, not this file.\n"
        "users:\n"
        "- jwt:\n"
        "    public_keys:\n"
        "    - |\n"
        "      -----BEGIN PUBLIC KEY-----\n"
        "      AAAA\n"
        "      -----END PUBLIC KEY-----\n"
        "  url_map:\n"
        "  - src_paths:\n"
        '    - "/api/v1/write"\n'
        '    - "/api/v1/import"\n'
        '    url_prefix: "http://127.0.0.1:8428/?extra_label={{.MetricsExtraLabels}}"\n'
    )


def test_migrating_to_oidc_changes_only_the_verification_block():
    with_key = build(settings(public_key=PUBLIC_KEY))
    with_oidc = build(settings(oidc_issuer="https://central.example.com"))

    assert '    oidc:\n      issuer: "https://central.example.com"\n' in with_oidc
    assert "public_keys" not in with_oidc
    # everything after the verification block is identical
    assert with_key.split("  url_map:\n")[1] == with_oidc.split("  url_map:\n")[1]


def test_skip_verify_is_spelled_out():
    assert "    skip_verify: true\n" in build(settings(skip_verify=True))


def test_query_paths_are_never_proxied():
    """A write token must not reach a read endpoint."""
    written = build(settings(public_key=PUBLIC_KEY))

    assert "/api/v1/query" not in written
    assert "/api/v1/query_range" not in written


def test_two_verification_modes_is_a_startup_failure():
    with pytest.raises(RuntimeError, match="accepts one"):
        build(settings(public_key=PUBLIC_KEY, oidc_issuer="https://central.example.com"))


def test_no_verification_configured_is_a_startup_failure():
    with pytest.raises(RuntimeError, match="No JWT verification"):
        build(settings())


def test_a_trailing_slash_on_the_store_does_not_double_up():
    written = build(VmauthSettings(victoria_url=URL + "/", public_key=PUBLIC_KEY))

    assert f'url_prefix: "{URL}/?extra_label=' in written


def test_skip_verify_reports_that_it_is_not_verifying():
    assert settings(skip_verify=True).is_verifying is False
    assert settings(public_key=PUBLIC_KEY).is_verifying is True


def test_settings_read_the_environment(monkeypatch):
    monkeypatch.setenv("DATUM_URL", URL)
    monkeypatch.setenv(ISSUER_VARIABLE, "https://central.example.com")
    monkeypatch.delenv(SKIP_VERIFY_VARIABLE, raising=False)

    assert VmauthSettings.from_env().mode == "oidc"
