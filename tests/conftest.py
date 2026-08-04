import jwt
import pytest
from fastapi.testclient import TestClient

from datum import Settings, create_app
from datum.api.internals import Identity, TokenVerifier
from datum.api.internals.providers import MetricProvider

SETTINGS = Settings(url="http://localhost:8428")

# A fixed throwaway keypair, so tests never generate one and both copies of this
# module agree on it. Never used anywhere but here.
PRIVATE_KEY = """\
-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCxgnC60m40MN/1
SYKwDM7iiCvi32O7jK52ojd51Ugk1bjVkMxi1Dbr2xd3d6EfKB83v6HLxLEdU4V/
y+pB2p2TKnYi9TdLNLCwRWSgamzumr8jrsfw8m3ZicJ9PiqKbJzBbZKkJxGGsjdf
fTeQb04wQy8DCxWGoE6qLhJgR7lPITaR23qQSo/LE4TB5Nq59YmvhNdz83/v5Q6o
ftIKX1wZdshOtS8h9uryqHgg56aSQgTPwR7CCDFsMYS2oOn9hr/R0WUn0Voe5I2f
XQRoh6+maKgMDYQvZyBp0ZP/bBOR3jCXxzjYJtRKrcnDgwoBiUNs+2hFVej6n5kk
1ytODiZrAgMBAAECgf8iq1dZJcBgcStMvQ7JU7cUh4QKy5avCssIYKZ1JTLx/swa
6i0BIHGZnzD2JGdTroJqYQM4yTHOiIGKdElMk2YzWBe6vCoQhjn8M5Fzw1WDRLYQ
QhLK/I537nAOBhZI8u2q2bvKU9cYd7ZY8BvqGdMrmfOUpJWPtb+nfVgZdei7i22i
s9gkQqf7Ki94mahXZuYFi1+imDGfWgtxOSD5F4sHYGHr7CLbfbYljt+iJHxFwSpc
KJB6NzuGS7v++x8LM85ue82s9zZEmxdS6CX6t2CXSy8NHvWQDpi/rAJmvgPRghzD
hWc23kzOeC6aMyuTRuk8rr5sLj4jkw3EJkHTQGECgYEA5MM78kMDst/0xp8khw/P
AAbUfCYEBpiJiFSFHZQtf0IDL/y+JIclx5z3S0+2RY0XfuF+izQgJSahSLi9VW1b
lYLa7aPM2RrVh18OCrgXZRU4jxUOb7sCyUALXy15iXDXeRiBNN3br1C/K86RXwOu
9jB8/RTRuPYarRZV72fO/1kCgYEAxqT+WwUPlACESj1y3jQV8wKUu6pCRQfDoPuQ
YYmLYVfdAlBnYsWvgVluguB4c2AY676Fhg8IQM0ZJgR3dbd4u4rrBg9wmWtkOc+t
1m6STh0cxUdbL6yg9uC4FbmefQS/ZC8667t2l0fpjjqrJwXNkkjQb8ViD6lLnYM5
bzquv2MCgYEA0Ku6UemJRTB+8nMWedEUzHxudPSkdXPM+LvIVUvmGJAZojtVIrLY
5nWrKlqC9HyYMxf0O3yH2fub4V8K7hL8GKytkVn6MQwGPR6bC3ITfRRXbEUTzx1y
lCtEdERh+doh4wdUTOoXS5tHVultt5L/lPhz+tNz3tk3Si32o5Q4wLkCgYA7kNZE
7OuS8eS5blu3jd7XE/sNmyxsDrv21fihhuEou3QmcX3O/IB4RR0CWdVEo5hVeLgJ
TxCmfdoAsG4x+mZVtn5rPs4A81cGjuQN3PI6QjiSX6dUUGukHBaXTSXdT0MlA5Sj
g384NfQvFiCkfvT53KPEIGgbUiS+gs8CL5KfCQKBgQCnhhauQ1P6b9BXRaeiiTEv
U53Q69U2TC6IjfxiAAs6s2sBpSZjpmyLznnFRUo/VfUZmVuAuEROf7qRrEiuOWQ6
+mqmfTgWBGcZJWz4T93ce07IxFH8pU7ROCDwFHjI4EHorHFSK71uQW3//mpvvpLc
SYQC0HT+ZTWRe9Nf2t+EtA==
-----END PRIVATE KEY-----
"""

PUBLIC_KEY = """\
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsYJwutJuNDDf9UmCsAzO
4ogr4t9ju4yudqI3edVIJNW41ZDMYtQ269sXd3ehHygfN7+hy8SxHVOFf8vqQdqd
kyp2IvU3SzSwsEVkoGps7pq/I67H8PJt2YnCfT4qimycwW2SpCcRhrI3X303kG9O
MEMvAwsVhqBOqi4SYEe5TyE2kdt6kEqPyxOEweTaufWJr4TXc/N/7+UOqH7SCl9c
GXbITrUvIfbq8qh4IOemkkIEz8EewggxbDGEtqDp/Ya/0dFlJ9FaHuSNn10EaIev
pmioDA2EL2cgadGT/2wTkd4wl8c42CbUSq3Jw4MKAYlDbPtoRVXo+p+ZJNcrTg4m
awIDAQAB
-----END PUBLIC KEY-----
"""


CLAIMS = {"vm_access": {"metrics_extra_labels": ["tenant_id=acme", "source_id=pilot_1"]}}
IDENTITY = Identity(labels={"tenant_id": "acme", "source_id": "pilot_1"})


def mint(claims: dict | None = None, key: str | None = None, headers: dict | None = None) -> str:
    """A JWT the way Central would sign one."""
    return jwt.encode(claims or CLAIMS, key or PRIVATE_KEY, algorithm="RS256", headers=headers)


TOKEN = mint()


def tamper(token: str) -> str:
    """Break the signature for real.

    Flipping the last character is not enough: a 2048-bit RSA signature is 256
    bytes, so base64url's final character carries two significant bits and four
    of them decode to the same signature. Mid-segment characters carry six.
    """
    header, payload, signature = token.split(".")
    index = len(signature) // 2
    swapped = "A" if signature[index] != "A" else "B"
    return f"{header}.{payload}.{signature[:index]}{swapped}{signature[index + 1:]}"


class FakeProvider(MetricProvider):
    """Stands in for a real store, so route tests do not depend on how far
    `VictoriaMetricsProvider` has been written."""

    def __init__(self, **options):
        self.options = options
        self.fetched: list = []

    def fetch(self, spec):
        self.fetched.append(spec)
        return []

    @property
    def metrics(self):
        return ["system_cpu_percent"]

    def get_labels(self, metric):
        return ["region"]

    def get_label_values(self, metric, label):
        return ["ap_south_1"]


@pytest.fixture
def tokens():
    return TokenVerifier(PUBLIC_KEY)


@pytest.fixture
def client(tokens):
    """Authenticated, the way a reader talks to the service."""
    app = create_app(SETTINGS, tokens=tokens)
    with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as test_client:
        app.state.store.provider = FakeProvider()
        yield test_client


@pytest.fixture
def anonymous():
    app = create_app(SETTINGS, tokens=TokenVerifier())
    with TestClient(app) as test_client:
        yield test_client
