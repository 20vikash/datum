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


def test_explain_returns_the_promql_without_fetching(client):
    response = client.post(
        "/v1/query/explain",
        json={"sql": "SELECT * FROM system_cpu_percent WHERE region = 'ap-south-1'"},
    )

    assert response.status_code == 200
    assert response.json()["promql"] == 'system_cpu_percent{region="ap-south-1"}'


def test_the_page_window_is_dropped(client):
    """BI tools paginate; over a relative window that is incoherent, so it goes."""
    response = client.post(
        "/v1/query/explain",
        json={
            "sql": "SELECT * FROM system_cpu_percent "
            "WHERE region = 'ap-south-1' LIMIT 100 OFFSET 200"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["promql"] == 'system_cpu_percent{region="ap-south-1"}'
    assert (body["limit"], body["offset"]) == (None, 0)


def test_refused_sql_is_a_400_not_a_500(client):
    response = client.post("/v1/query/explain", json={"sql": "SELECT avg(value) FROM cpu"})

    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


def test_malformed_body_is_a_422(client):
    response = client.post("/v1/query/explain", json={})

    assert response.status_code == 422


def test_only_read_routes_are_published(client):
    """The write path lives in vmauth, so it must not appear in the schema."""
    paths = client.get("/v1/openapi.json").json()["paths"]

    assert sorted(paths) == [
        "/v1/metrics",
        "/v1/metrics/{metric}/columns",
        "/v1/query",
        "/v1/query/explain",
    ]


def test_query_shapes_what_the_provider_returns(client):
    response = client.post("/v1/query", json={"sql": "SELECT * FROM cpu"})

    assert response.status_code == 200
    assert response.json()["rows"] == []
