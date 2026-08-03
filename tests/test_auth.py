import pytest

from datum.api.internals import Identity, LabelConflict, TokenStore
from tests.conftest import IDENTITY, TOKEN


def test_a_token_resolves_to_its_identity(tokens):
    assert tokens.resolve(TOKEN) == IDENTITY


def test_an_unknown_token_resolves_to_nothing(tokens):
    assert tokens.resolve("not-a-token") is None


def test_revoking_takes_effect_immediately(tokens):
    tokens.revoke(TOKEN)

    assert tokens.resolve(TOKEN) is None


def test_tokens_are_never_held_in_the_clear():
    store = TokenStore({TOKEN: IDENTITY})

    assert TOKEN not in repr(store.__dict__)
    assert TokenStore.digest(TOKEN) in store.__dict__["_by_hash"]


def test_v1_refuses_an_anonymous_caller(anonymous):
    response = anonymous.post("/v1/ingest", json={"samples": []})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_v1_refuses_an_unknown_token(anonymous):
    response = anonymous.get("/v1/metrics", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_health_stays_open(anonymous):
    assert anonymous.get("/health").status_code == 200


def test_auth_runs_before_validation(anonymous):
    """A bad body from a stranger is a 401, never a 422 describing our schema."""
    response = anonymous.post("/v1/ingest", json={"nonsense": True})

    assert response.status_code == 401


def test_the_token_stamps_identity_onto_every_sample(client, tokens):
    provider = client.app.state.store.provider
    written = []
    provider.write = lambda samples: written.extend(samples) or len(samples)

    client.post("/v1/ingest", json={"samples": [{"metric": "cpu", "value": 1.0, "ts": "2026-08-04T12:00:00Z"}]})

    assert written[0].labels == {
        "region": "ap_south_1",
        "tenant_id": "acme",
        "source_id": "pilot_1",
    }


def test_claiming_a_label_the_token_fixes_is_refused(client):
    response = client.post(
        "/v1/ingest",
        json={
            "samples": [
                {
                    "metric": "cpu",
                    "value": 1.0,
                    "ts": "2026-08-04T12:00:00Z",
                    "labels": {"region": "elsewhere"},
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "region" in response.json()["detail"]


def test_an_identity_carries_no_labels_by_default():
    assert Identity(tenant="t", source="s").labels == {}


def test_stamp_adds_tenant_and_source():
    identity = Identity(tenant="acme", source="pilot_1")

    assert identity.stamp({"disk": "sda"}) == {
        "disk": "sda",
        "tenant_id": "acme",
        "source_id": "pilot_1",
    }


def test_stamp_keeps_labels_the_token_does_not_fix():
    stamped = IDENTITY.stamp({"disk": "sda"})

    assert stamped["disk"] == "sda"
    assert stamped["region"] == "ap_south_1"


def test_stamp_refuses_a_claimed_label():
    with pytest.raises(LabelConflict, match="region"):
        IDENTITY.stamp({"region": "elsewhere"})
