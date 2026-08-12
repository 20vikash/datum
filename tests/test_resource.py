import pytest
from fastapi.testclient import TestClient

from datum import create_app
from tests.conftest import SETTINGS, mint

ADMIN = {"admin": True}


@pytest.fixture
def admin(tokens, provider):
    app = create_app(SETTINGS, tokens=tokens, provider=provider)
    with TestClient(app, headers={"Authorization": f"Bearer {mint(ADMIN)}"}) as test_client:
        yield test_client


def test_an_admin_registers_a_resource(admin, provider):
    response = admin.post("/v1/resource/add", json={"resource_id": "vm-1", "status": "Active"})

    assert response.status_code == 200
    assert response.json() == {"accepted": 1}
    assert provider.resources == [("vm-1", "Active")]


def test_the_resource_id_comes_from_the_body_not_the_token(admin, provider):
    """The opposite of ingest: an admin speaks for the fleet, so it names the machine."""
    admin.post("/v1/resource/add", json={"resource_id": "vm-2", "status": "Pending"})

    assert provider.resources == [("vm-2", "Pending")]


def test_a_status_update_reaches_the_store(admin, provider):
    response = admin.put("/v1/resource/vm-1/status", json={"status": "Pending"})

    assert response.status_code == 200
    assert provider.resources == [("vm-1", "Pending")]


def test_deleting_marks_it_terminated(admin, provider):
    """The row stays: its samples outlive it, and datum holds no ALTER grant."""
    response = admin.delete("/v1/resource/vm-1")

    assert response.status_code == 200
    assert provider.resources == [("vm-1", "Terminated")]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/resource/add", {"resource_id": "vm-1", "status": "Active"}),
        ("put", "/v1/resource/vm-1/status", {"status": "Active"}),
        ("delete", "/v1/resource/vm-1", None),
    ],
)
def test_a_machine_token_cannot_touch_resources(client, provider, method, path, body):
    """A write token ingests its own samples; it does not manage the fleet's roster."""
    response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)

    assert response.status_code == 403
    assert "admin" in response.json()["detail"]
    assert provider.resources == []


def test_an_anonymous_caller_is_refused_before_validation(anonymous):
    response = anonymous.post("/v1/resource/add", json={"nonsense": True})

    assert response.status_code == 401


def test_an_unknown_status_is_refused_by_the_schema(admin, provider):
    response = admin.post("/v1/resource/add", json={"resource_id": "vm-1", "status": "Melted"})

    assert response.status_code == 422
    assert provider.resources == []


def test_an_empty_resource_id_is_refused(admin, provider):
    response = admin.post("/v1/resource/add", json={"resource_id": "", "status": "Active"})

    assert response.status_code == 422
    assert provider.resources == []


def test_an_admin_without_a_resource_id_still_cannot_ingest(admin, provider):
    """It would stamp an empty resource_id on every row."""
    sample = {"samples": [{"metric": "cpu", "value": 1.0, "ts": "2026-08-05T10:00:00Z"}]}

    response = admin.post("/v1/ingest", json=sample)

    assert response.status_code == 403
    assert provider.written == []
