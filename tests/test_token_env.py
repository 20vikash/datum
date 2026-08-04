from datum.api.internals import TokenVerifier
from datum.api.internals.auth import PUBLIC_KEY_VARIABLE
from tests.conftest import PUBLIC_KEY, TOKEN


def test_the_key_loads_from_the_environment(monkeypatch):
    monkeypatch.setenv(PUBLIC_KEY_VARIABLE, PUBLIC_KEY)

    verifier = TokenVerifier.from_env()

    assert verifier.is_configured
    assert verifier.resolve(TOKEN) is not None


def test_unset_means_no_key(monkeypatch):
    monkeypatch.delenv(PUBLIC_KEY_VARIABLE, raising=False)

    assert TokenVerifier.from_env().is_configured is False


def test_whitespace_is_not_a_key(monkeypatch):
    monkeypatch.setenv(PUBLIC_KEY_VARIABLE, "   \n  ")

    assert TokenVerifier.from_env().is_configured is False
