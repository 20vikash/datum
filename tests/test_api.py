from fastapi.testclient import TestClient

from datum import Settings, create_app

SETTINGS = Settings(url="http://localhost:8428")


def test_health_reports_ok():
    with TestClient(create_app(SETTINGS)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_are_held_on_the_app():
    app = create_app(SETTINGS)

    assert app.state.settings.url == SETTINGS.url
