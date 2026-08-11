import pytest

from datum.api.limiter import RateLimiter, RateLimitKey

INGEST = "/v1/ingest"
SAMPLE = {"samples": [{"metric": "cpu", "value": 1.0, "ts": "2026-08-05T10:00:00Z"}]}
PATH = "/v1/ingest/remote"

# What ingest.py asks for.
WRITES = 12


LIMIT = 3
PERIOD = 60


class Clock:
    """Time a test moves by hand, so no test waits on the wall clock."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def limiter(clock):
    return RateLimiter(clock=clock)


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


def test_the_window_reopens_once_the_period_passes(limiter, clock):
    limiter.get_retry_after("acme", PATH, 1, PERIOD)
    assert limiter.get_retry_after("acme", PATH, 1, PERIOD) > 0

    clock.advance(PERIOD)

    assert limiter.get_retry_after("acme", PATH, 1, PERIOD) == 0


def test_a_route_refuses_once_the_budget_is_spent(client, provider):
    for _ in range(WRITES):
        assert client.post(INGEST, json=SAMPLE).status_code == 200

    response = client.post(INGEST, json=SAMPLE)

    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_the_limit_is_per_tenant_through_the_api(client, other_tenant):
    for _ in range(WRITES + 1):
        client.post(INGEST, json=SAMPLE)

    assert other_tenant.post(INGEST, json=SAMPLE).status_code == 200


def test_the_two_ingest_routes_are_counted_apart(client):
    """Same budget, separate windows: JSON and remote write are two routes."""
    for _ in range(WRITES + 1):
        client.post(INGEST, json=SAMPLE)

    assert client.post("/v1/ingest/remote", content=b"nonsense").status_code != 429


def test_an_unknown_token_is_a_401_not_a_429(anonymous):
    for _ in range(WRITES + 5):
        response = anonymous.post(INGEST, json=SAMPLE)

    assert response.status_code == 401


def test_callers_who_stop_coming_back_are_retired(limiter, clock):
    """They sink to the front as others are served, and are dropped there."""
    for index in range(20):
        limiter.get_retry_after(f"gone-{index}", PATH, LIMIT, 10)
    clock.advance(11)

    for index in range(20):
        limiter.get_retry_after(f"here-{index}", PATH, LIMIT, 60)

    held = [key.caller for key in limiter.ratelimit_windows]
    assert not any(caller.startswith("gone") for caller in held)


def test_a_live_caller_is_never_retired_to_make_room(limiter):
    """No cap, so nobody is refused or reset for holding a window."""
    limiter.get_retry_after("early", PATH, LIMIT, 60)

    for index in range(500):
        assert limiter.get_retry_after(f"later-{index}", PATH, LIMIT, 60) == 0

    assert RateLimitKey("early", PATH) in limiter.ratelimit_windows
