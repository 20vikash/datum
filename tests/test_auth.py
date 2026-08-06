import time

from datum.api.internals import Identity, TokenVerifier
from tests.conftest import CLAIMS, IDENTITY, PUBLIC_KEY, TOKEN, mint, tamper


def test_a_signed_token_resolves_to_its_identity(tokens):
    assert tokens.resolve(TOKEN) == IDENTITY


def test_a_token_signed_by_someone_else_is_refused(tokens):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )

    assert tokens.resolve(mint(key=other)) is None


def test_a_tampered_signature_is_refused(tokens):
    assert tokens.resolve(tamper(TOKEN)) is None


def test_an_expired_token_is_refused(tokens):
    stale = mint({"exp": int(time.time()) - 60, **CLAIMS})

    assert tokens.resolve(stale) is None


def test_nonsense_is_refused_rather_than_raised(tokens):
    assert tokens.resolve("not-a-jwt") is None


def test_without_a_key_nothing_resolves():
    assert TokenVerifier().resolve(TOKEN) is None


def test_the_identity_is_the_resource_id_and_what_it_may_do():
    identity = Identity.from_claims({"resource_id": "acme", "access": ["read", "write"]})

    assert identity.resource_id == "acme"
    assert (identity.can_read, identity.can_write) == (True, True)


def test_access_may_be_written_as_one_string():
    claims = {"resource_id": "acme", "access": "read write"}

    assert Identity.from_claims(claims).can_read is True


def test_a_token_claiming_no_access_may_do_nothing():
    identity = Identity.from_claims({"resource_id": "acme"})

    assert (identity.can_read, identity.can_write) == (False, False)


def test_read_and_write_are_separate():
    reader = Identity.from_claims({"resource_id": "acme", "access": ["read"]})

    assert (reader.can_read, reader.can_write) == (True, False)


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


def test_a_token_without_a_resource_id_is_no_identity_at_all(tokens):
    """Reads are scoped by it and writes are stamped with it, so a token
    without one has nothing to address."""
    assert tokens.resolve(mint({"access": ["read", "write"]})) is None


def test_the_public_key_is_what_gates_access():
    assert TokenVerifier(PUBLIC_KEY).is_configured is True
    assert TokenVerifier().is_configured is False
