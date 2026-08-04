import pytest

from datum.api.internals import TokenVerifier
from datum.api.internals.auth import PUBLIC_KEY_FILE_VARIABLE
from tests.conftest import PUBLIC_KEY, TOKEN


def test_the_key_is_read_from_the_file_the_variable_names(monkeypatch, tmp_path):
    key = tmp_path / "central.pub"
    key.write_text(PUBLIC_KEY)
    monkeypatch.setenv(PUBLIC_KEY_FILE_VARIABLE, str(key))

    verifier = TokenVerifier.from_env()

    assert verifier.is_configured
    assert verifier.resolve(TOKEN) is not None


def test_unset_means_no_key(monkeypatch):
    monkeypatch.delenv(PUBLIC_KEY_FILE_VARIABLE, raising=False)

    assert TokenVerifier.from_env().is_configured is False


def test_a_missing_file_is_a_startup_failure(monkeypatch, tmp_path):
    """Better than starting up and answering 401 to everyone."""
    monkeypatch.setenv(PUBLIC_KEY_FILE_VARIABLE, str(tmp_path / "absent.pub"))

    with pytest.raises(RuntimeError, match="not a file"):
        TokenVerifier.from_env()
