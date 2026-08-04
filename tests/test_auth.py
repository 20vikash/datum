import time

from datum.api.internals import Identity, TokenVerifier
from tests.conftest import IDENTITY, PUBLIC_KEY, TOKEN, mint


def test_a_signed_token_resolves_to_its_identity(tokens):
    assert tokens.resolve(TOKEN) == IDENTITY


def test_a_token_signed_by_someone_else_is_refused(tokens):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    assert tokens.resolve(mint(key=other)) is None


def test_a_tampered_signature_is_refused(tokens):
    tampered = TOKEN[:-1] + ("A" if TOKEN[-1] != "A" else "B")

    assert tokens.resolve(tampered) is None


def test_an_expired_token_is_refused(tokens):
    stale = mint({"exp": int(time.time()) - 60, "vm_access": {}})

    assert tokens.resolve(stale) is None


def test_nonsense_is_refused_rather_than_raised(tokens):
    assert tokens.resolve("not-a-jwt") is None


def test_without_a_key_nothing_resolves():
    assert TokenVerifier().resolve(TOKEN) is None


def test_labels_come_from_the_access_claim():
    identity = Identity.from_claims(
        {"vm_access": {"metrics_extra_labels": ["tenant_id=acme", "region=blr"]}}
    )

    assert identity.labels == {"tenant_id": "acme", "region": "blr"}


def test_a_claim_without_labels_is_an_empty_identity():
    assert Identity.from_claims({"vm_access": {}}).labels == {}
    assert Identity.from_claims({}).labels == {}


def test_v1_refuses_an_anonymous_caller(anonymous):
    response = anonymous.post("/v1/query", json={"sql": "SELECT * FROM cpu"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_v1_refuses_an_unknown_token(anonymous):
    response = anonymous.get("/v1/metrics", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_health_stays_open(anonymous):
    assert anonymous.get("/health").status_code == 200


def test_auth_runs_before_validation(anonymous):
    """A bad body from a stranger is a 401, never a 422 describing our schema."""
    response = anonymous.post("/v1/query", json={"nonsense": True})

    assert response.status_code == 401


def test_writing_is_not_served_here(client):
    """Producers go to vmauth. Nothing in this service accepts samples."""
    assert client.post("/v1/ingest", json={"samples": []}).status_code == 404
    assert client.post("/v1/write", content=b"").status_code == 404


def test_the_public_key_is_what_gates_access():
    assert TokenVerifier(PUBLIC_KEY).is_configured is True
    assert TokenVerifier().is_configured is False
