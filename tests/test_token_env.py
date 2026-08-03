import json

import pytest

from datum.api.internals import Identity, TokenStore
from datum.api.internals.auth import TOKENS_VARIABLE

RECORD = {"tenant": "acme", "source": "pilot_1", "labels": {"region": "ap_south_1"}}


def test_tokens_load_from_the_environment(monkeypatch):
    monkeypatch.setenv(TOKENS_VARIABLE, json.dumps({"secret": RECORD, "other": RECORD}))

    store = TokenStore.from_env()

    assert store.count == 2
    assert store.resolve("secret") == Identity(**RECORD)


def test_unset_means_no_tokens(monkeypatch):
    monkeypatch.delenv(TOKENS_VARIABLE, raising=False)

    assert TokenStore.from_env().count == 0


def test_malformed_fails_at_startup_rather_than_silently_empty(monkeypatch):
    monkeypatch.setenv(TOKENS_VARIABLE, "{not json")

    with pytest.raises(RuntimeError, match="malformed"):
        TokenStore.from_env()
