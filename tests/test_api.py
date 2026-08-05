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
    paths = client.get("/v1/openapi.json").json()["paths"]

    assert sorted(paths) == [
        "/v1/ingest",
        "/v1/ingest/remote",
        "/v1/metrics",
        "/v1/metrics/{metric}/columns",
        "/v1/query",
    ]


def test_the_schema_is_ready_before_the_first_request(provider, client):
    assert provider.prepared


def test_query_passes_the_sql_through_untouched(client, provider):
    sql = "SELECT ts, value FROM datum.samples WHERE metric = 'cpu'"

    response = client.post("/v1/query", json={"sql": sql})

    assert response.status_code == 200
    assert provider.fetched == [sql]
    assert response.json() == {"columns": ["ts", "value"], "rows": [], "truncated": False}


def test_malformed_body_is_a_422(client):
    assert client.post("/v1/query", json={}).status_code == 422


def test_columns_flatten_the_label_map(client):
    response = client.get("/v1/metrics/system_cpu_percent/columns")

    assert response.status_code == 200
    assert response.json()["columns"] == ["ts", "metric", "resource_id", "region", "value"]


def test_metrics_are_listed(client):
    assert client.get("/v1/metrics").json() == {"metrics": ["system_cpu_percent"]}
