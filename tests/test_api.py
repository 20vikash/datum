def test_health_is_unversioned(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_absent_from_the_schema(client):
    paths = client.get("/v1/openapi.json").json()["paths"]

    assert "/health" not in paths


def test_every_documented_path_is_versioned(client):
    paths = client.get("/v1/openapi.json").json()["paths"]

    assert paths
    assert all(path.startswith("/v1/") for path in paths)


def test_the_published_routes(client):
    """Write-only: reads go to ClickHouse directly, so datum publishes none."""
    paths = client.get("/v1/openapi.json").json()["paths"]

    assert sorted(paths) == ["/v1/ingest", "/v1/ingest/remote"]


def test_the_schema_is_ready_before_the_first_request(provider, client):
    assert provider.prepared


def test_malformed_body_is_a_422(client):
    assert client.post("/v1/ingest", json={}).status_code == 422
