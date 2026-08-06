import cramjam
import pytest

from datum.api.internals.remote import BodyTooLarge, decode
from datum.api.middleware import BodyLimit
from datum.config import MAX_BODY, MAX_DECOMPRESSED, Settings

RESOURCE = "acme"


def scope(method="POST", **headers):
    raw = [(name.encode(), value.encode()) for name, value in headers.items()]
    return {"type": "http", "method": method, "headers": raw}


def refusal(**arguments):
    return BodyLimit(app=None).get_refusal(scope(**arguments))


def test_a_body_within_the_cap_is_routed():
    assert refusal(**{"content-length": str(MAX_BODY)}) is None


def test_a_body_over_the_cap_never_reaches_the_route():
    response = refusal(**{"content-length": str(MAX_BODY + 1)})

    assert response.status_code == 413


def test_a_body_of_unknown_length_is_refused():
    """A limit that is skipped by omitting a header is not a limit."""
    assert refusal().status_code == 411


def test_a_content_length_that_is_not_a_number_is_refused():
    assert refusal(**{"content-length": "lots"}).status_code == 411


def test_a_read_carries_no_body_and_is_left_alone():
    assert refusal(method="GET") is None


def test_an_oversized_body_is_refused_before_the_route_runs(client, provider):
    response = client.post("/v1/ingest/remote", content=b"x" * (MAX_BODY + 1))

    assert response.status_code == 413
    assert provider.written == []


def test_a_small_body_that_decompresses_huge_is_refused(provider):
    """Snappy runs to about 20:1, so the body cap does not bound this on its own."""
    bomb = bytes(cramjam.snappy.compress_raw(b"\0" * (MAX_DECOMPRESSED + 1)))

    assert len(bomb) < MAX_BODY
    with pytest.raises(BodyTooLarge, match=str(MAX_DECOMPRESSED)):
        decode(bomb, RESOURCE)


def test_the_bomb_is_never_allocated_to_answer_it(client, provider):
    bomb = bytes(cramjam.snappy.compress_raw(b"\0" * (MAX_DECOMPRESSED + 1)))

    assert client.post("/v1/ingest/remote", content=bomb).status_code == 413
    assert provider.written == []


def test_a_table_name_that_would_need_quoting_is_refused_at_startup():
    """It would not match the table ClickHouse resolves, so the tenant filter
    would attach to nothing and reads would go unscoped in silence."""
    with pytest.raises(ValueError, match="DATUM_CLICKHOUSE_TABLE"):
        Settings(host="localhost", table="samples; DROP")


def test_a_database_name_is_held_to_the_same_rule():
    with pytest.raises(ValueError, match="DATUM_CLICKHOUSE_DATABASE"):
        Settings(host="localhost", database="datum-1")
