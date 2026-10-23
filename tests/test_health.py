from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
    assert "X-Request-ID" in resp.headers

def test_database_health_endpoint():
    resp = client.get("/health/db")
    assert resp.status_code == 200
    assert resp.json()["database"] == "connected"
