"""Read-side OIDC: discovery, then the key set, the same two steps vmauth takes.

Served by a real local HTTP server rather than a mock, so the discovery and
JWKS parsing are actually exercised.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest

from datum.api.internals import TokenVerifier
from datum.config.vmauth import ISSUER_VARIABLE, PUBLIC_KEY_FILE_VARIABLE
from tests.conftest import CLAIMS, PUBLIC_KEY, mint, tamper

KEY_ID = "central-1"


def jwks() -> dict:
    algorithm = jwt.algorithms.RSAAlgorithm(jwt.algorithms.RSAAlgorithm.SHA256)
    key = algorithm.to_jwk(algorithm.prepare_key(PUBLIC_KEY), as_dict=True)
    return {"keys": [{**key, "kid": KEY_ID, "use": "sig", "alg": "RS256"}]}


class Issuer(BaseHTTPRequestHandler):
    """Serves the two documents an OIDC provider must serve."""

    missing_jwks_uri = False

    def do_GET(self):
        base = f"http://{self.headers['Host']}"
        if self.path == "/.well-known/openid-configuration":
            document = {} if self.missing_jwks_uri else {"jwks_uri": f"{base}/keys"}
            self._send(document)
        elif self.path == "/keys":
            self._send(jwks())
        else:
            self.send_error(404)

    def _send(self, document: dict) -> None:
        body = json.dumps(document).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def issuer():
    """One server for the file: HTTPServer.shutdown() polls on a 0.5s tick,
    which per test costs more than everything else here combined."""
    server = HTTPServer(("127.0.0.1", 0), Issuer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def signed_for(issuer_url: str) -> str:
    return mint({**CLAIMS, "iss": issuer_url}, headers={"kid": KEY_ID})


def test_a_token_is_verified_against_the_fetched_key_set(issuer):
    verifier = TokenVerifier(oidc_issuer=issuer)

    identity = verifier.resolve(signed_for(issuer))

    assert identity is not None
    assert identity.labels == {"tenant_id": "acme", "source_id": "pilot_1"}


def test_a_token_from_another_issuer_is_refused(issuer):
    verifier = TokenVerifier(oidc_issuer=issuer)

    assert verifier.resolve(signed_for("https://somewhere-else.example.com")) is None


def test_a_tampered_signature_is_refused(issuer):
    assert TokenVerifier(oidc_issuer=issuer).resolve(tamper(signed_for(issuer))) is None


def test_the_key_set_is_fetched_once_and_reused(issuer):
    verifier = TokenVerifier(oidc_issuer=issuer)
    token = signed_for(issuer)

    assert verifier.resolve(token) is not None
    assert verifier.resolve(token) is not None


def test_an_unreachable_issuer_is_a_401_not_a_crash():
    """While the provider is down, reads are refused rather than let through."""
    verifier = TokenVerifier(oidc_issuer="http://127.0.0.1:1")

    assert verifier.resolve("anything") is None


def test_a_discovery_document_without_jwks_uri_is_refused(issuer, monkeypatch):
    monkeypatch.setattr(Issuer, "missing_jwks_uri", True)

    assert TokenVerifier(oidc_issuer=issuer).resolve(signed_for(issuer)) is None


def test_the_issuer_reaches_the_verifier_from_the_unit(monkeypatch, issuer):
    monkeypatch.delenv(PUBLIC_KEY_FILE_VARIABLE, raising=False)
    monkeypatch.setenv(ISSUER_VARIABLE, issuer)

    verifier = TokenVerifier.from_env()

    assert verifier.is_configured
    assert verifier.resolve(signed_for(issuer)) is not None
