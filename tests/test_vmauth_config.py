"""The vmauth config is the whole write-path security boundary, so its exact
text is asserted rather than its shape."""

from pathlib import Path

import pytest

from datum.config import VmauthSettings
from datum.config.vmauth import EXTRA_FILTERS

KEY_PATH = Path("/home/frappe/services/central.pub")

URL = "http://127.0.0.1:8428"


def settings(**overrides) -> VmauthSettings:
    return VmauthSettings(victoria_url=URL, **overrides)


def config(built: VmauthSettings) -> str:
    return built.config


def test_public_key_config_is_exact():
    written = config(settings(public_key_path=KEY_PATH))

    assert written == (
        "# Written by bootstrap.py. Re-run it to change this; edits here are lost.\n"
        "users:\n"
        "- jwt:\n"
        "    public_key_files:\n"
        "    - /home/frappe/services/central.pub\n"
        "    match_claims:\n"
        "      scope: datum\n"
        "  url_map:\n"
        "  - src_paths:\n"
        "    - /api/v1/write\n"
        "    - /api/v1/import\n"
        "    url_prefix: http://127.0.0.1:8428/?extra_label={{.MetricsExtraLabels}}\n"
    )


def test_migrating_to_oidc_changes_only_the_verification_block():
    with_key = config(settings(public_key_path=KEY_PATH))
    with_oidc = config(settings(oidc_issuer="https://central.example.com"))

    assert "    oidc:\n      issuer: https://central.example.com\n" in with_oidc
    assert "public_keys" not in with_oidc
    # everything after the verification block is identical
    assert with_key.split("  url_map:\n")[1] == with_oidc.split("  url_map:\n")[1]


def test_skip_verify_is_spelled_out():
    assert "    skip_verify: true\n" in config(settings(skip_verify=True))


def test_query_paths_are_never_proxied():
    """A write token must not reach a read endpoint."""
    written = config(settings(public_key_path=KEY_PATH))

    assert "/api/v1/query" not in written
    assert "/api/v1/query_range" not in written


def test_direct_reads_config_is_exact():
    """The read map is the whole read boundary, so assert its text."""
    written = config(settings(public_key_path=KEY_PATH, direct_reads=True))

    assert written == (
        "# Written by bootstrap.py. Re-run it to change this; edits here are lost.\n"
        "users:\n"
        "- jwt:\n"
        "    public_key_files:\n"
        "    - /home/frappe/services/central.pub\n"
        "    match_claims:\n"
        "      scope: datum\n"
        "  url_map:\n"
        "  - src_paths:\n"
        "    - /api/v1/write\n"
        "    - /api/v1/import\n"
        "    url_prefix: http://127.0.0.1:8428/?extra_label={{.MetricsExtraLabels}}\n"
        "  - src_paths:\n"
        "    - /api/v1/query\n"
        "    - /api/v1/query_range\n"
        "    - /api/v1/series\n"
        "    - /api/v1/labels\n"
        "    - /api/v1/label/[^/]+/values\n"
        "    url_prefix: http://127.0.0.1:8428/?extra_filters={{.MetricsExtraFilters}}\n"
    )


def test_direct_reads_are_off_unless_asked_for():
    assert "url_map:\n  - src_paths" in config(settings(public_key_path=KEY_PATH))
    assert "extra_filters" not in config(settings(public_key_path=KEY_PATH))


def test_a_read_is_always_filtered():
    """An unfiltered read endpoint is the whole risk, so the filter is never absent."""
    written = config(settings(public_key_path=KEY_PATH, direct_reads=True))

    reads = written.split("extra_label={{.MetricsExtraLabels}}\n")[1]
    assert "/api/v1/query" in reads
    assert f"extra_filters={EXTRA_FILTERS}" in reads


def test_writes_keep_their_own_prefix_when_reads_are_on():
    """Reads must not borrow the write map's extra_label, or writes stop being stamped."""
    written = config(settings(public_key_path=KEY_PATH, direct_reads=True))

    assert written.count("extra_label={{.MetricsExtraLabels}}") == 1
    assert written.count("extra_filters={{.MetricsExtraFilters}}") == 1


def test_two_verification_modes_is_a_startup_failure():
    with pytest.raises(RuntimeError, match="accepts one"):
        config(settings(public_key_path=KEY_PATH, oidc_issuer="https://central.example.com"))


def test_no_verification_configured_is_a_startup_failure():
    with pytest.raises(RuntimeError, match="No JWT verification"):
        config(settings())


def test_a_trailing_slash_on_the_store_does_not_double_up():
    written = config(VmauthSettings(victoria_url=URL + "/", public_key_path=KEY_PATH))

    assert f"url_prefix: {URL}/?extra_label=" in written


def test_skip_verify_reports_that_it_is_not_verifying():
    assert settings(skip_verify=True).is_verifying is False
    assert settings(public_key_path=KEY_PATH).is_verifying is True


def test_the_scope_gates_which_tokens_may_write():
    """Central signs bench and enrolment tokens with the same key as datum's."""
    written = config(settings(public_key_path=KEY_PATH))

    assert "    match_claims:\n      scope: datum\n" in written


def test_match_claims_is_a_sibling_of_the_key_block_not_a_child():
    """vmauth has no match_claims inside `oidc`; nesting it is a startup failure."""
    written = config(settings(oidc_issuer="https://central.example.com"))

    assert "      issuer: https://central.example.com\n    match_claims:\n" in written


def test_an_empty_scope_accepts_anything_the_key_signed():
    assert "match_claims" not in config(settings(public_key_path=KEY_PATH, scope=""))
