from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_app_name() -> None:
    client = TestClient(create_app(Settings(app_name="ClaimsWatch")))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["app"] == "ClaimsWatch"
