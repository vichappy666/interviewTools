def test_health_returns_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert "env" in body


def test_health_env_is_string(client):
    response = client.get("/api/health")
    assert isinstance(response.json()["env"], str)
