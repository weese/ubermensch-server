"""The HTTP surface with the echo provider: auth, rail, streaming shape."""
import json

from fastapi.testclient import TestClient

from app.main import app

TOKEN = "test-token-test-token-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def client():
    return TestClient(app)


def test_health_is_open_and_says_what_runs():
    with client() as c:
        r = c.get("/v1/health")
    assert r.status_code == 200 and r.json()["provider"] == "echo" and "token" not in r.text


def test_ping_needs_the_token():
    with client() as c:
        assert c.post("/v1/ping").status_code == 401
        assert c.post("/v1/ping", headers={"Authorization": "Bearer wrong-wrong-wrong-wrong-wrong"}).status_code == 401
        r = c.post("/v1/ping", headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True


def test_chat_round_trip_and_rail():
    with client() as c:
        r = c.post("/v1/chat", headers=AUTH, json={"messages": [{"role": "user", "content": "how was my week"}]})
        assert r.status_code == 200 and "how was my week" in r.json()["reply"] and r.json()["escalate"] is False
        r = c.post("/v1/chat", headers=AUTH, json={"messages": [{"role": "user", "content": "I have chest pain"}]})
        assert r.json()["escalate"] is True and r.json()["reply"].startswith("That is not something")
        r = c.post("/v1/chat", headers=AUTH, json={"messages": [{"role": "assistant", "content": "x"}]})
        assert r.status_code == 400


def test_stream_is_ndjson_ending_in_done():
    with client() as c:
        r = c.post("/v1/chat/stream", headers=AUTH, json={"messages": [{"role": "user", "content": "hello"}], "deep": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(l) for l in r.text.splitlines() if l.strip()]
    assert lines[0] == {"type": "thinking"}
    assert lines[-1] == {"type": "done", "escalate": False}
    assert "hello" in "".join(e.get("delta", "") for e in lines if e["type"] == "text")
