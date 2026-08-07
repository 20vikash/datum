import time

import pytest

from datum.api.limiter import RateLimiter
from datum.api.routes.v1.ingest import WRITES
from datum.api.routes.v1.query import LISTINGS, READS

PATH = "/v1/query"
BODY = {"sql": "SELECT 1"}


LIMIT = 3
PERIOD = 60


@pytest.fixture
def limiter():
    return RateLimiter()


def test_requests_under_the_limit_are_let_through(limiter):
    assert [limiter.get_retry_after("acme", PATH, LIMIT, PERIOD) for _ in range(3)] == [0, 0, 0]


def test_the_request_past_the_limit_is_refused(limiter):
    for _ in range(3):
        limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)

    assert limiter.get_retry_after("acme", PATH, LIMIT, PERIOD) > 0


def test_a_refusal_says_how_long_to_wait(limiter):
    for _ in range(4):
        retry_after = limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)

    assert 0 < retry_after <= 60


def test_a_refused_request_does_not_extend_the_window(limiter):
    """Counting a refusal would push the window out, so a caller at the limit
    could never get back in."""
    for _ in range(3):
        limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)
    first = limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)
    for _ in range(50):
        limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)

    assert limiter.get_retry_after("acme", PATH, LIMIT, PERIOD) <= first


def test_one_tenant_cannot_spend_another_budget(limiter):
    for _ in range(3):
        limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)

    assert limiter.get_retry_after("other", PATH, LIMIT, PERIOD) == 0


def test_routes_are_counted_apart(limiter):
    for _ in range(3):
        limiter.get_retry_after("acme", PATH, LIMIT, PERIOD)

    assert limiter.get_retry_after("acme", "/v1/ingest", LIMIT, PERIOD) == 0


def test_the_window_reopens_once_the_period_passes():
    limiter = RateLimiter()
    limiter.get_retry_after("acme", PATH, 1, 0.01)
    assert limiter.get_retry_after("acme", PATH, 1, 0.01) > 0

    time.sleep(0.02)

    assert limiter.get_retry_after("acme", PATH, 1, 0.01) == 0


def test_one_budget_covers_every_url_a_route_answers(client, provider):
    """Keyed on the route template: without that, each metric name would get a
    budget of its own and the route would be unlimited."""
    for index in range(LISTINGS):
        assert client.get(f"/v1/metrics/metric_{index}/columns").status_code == 200

    assert client.get("/v1/metrics/another_one/columns").status_code == 429


def test_each_route_carries_its_own_budget(client, provider):
    """`/v1/query` is charged more dearly than an ingest, so spending one does
    not spend the other."""
    for _ in range(READS + 1):
        client.post(PATH, json=BODY)

    sample = {"metric": "cpu", "value": 1.0, "ts": "2026-08-05T10:00:00Z"}
    assert client.post("/v1/ingest", json={"samples": [sample]}).status_code == 200
    assert WRITES > READS


def test_a_route_refuses_once_the_budget_is_spent(client, provider):
    for _ in range(READS):
        assert client.post(PATH, json=BODY).status_code == 200

    response = client.post(PATH, json=BODY)

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_the_limit_is_per_tenant_through_the_api(client, other_tenant):
    for _ in range(READS + 1):
        client.post(PATH, json=BODY)

    assert other_tenant.post(PATH, json=BODY).status_code == 200


def test_an_unknown_token_is_a_401_not_a_429(anonymous):
    for _ in range(READS + 5):
        response = anonymous.post(PATH, json=BODY)

    assert response.status_code == 401
