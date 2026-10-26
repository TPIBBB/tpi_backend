import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from civsim.api.server import create_app
from civsim.config import SimConfig
from civsim.world import SimulationEngine


def test_tick_through_api():
    client = TestClient(create_app(SimulationEngine(SimConfig())))
    alive = client.post("/admin/begin-tick").json()["alive"]
    agent_id = alive[0]

    assert client.get(f"/agents/{agent_id}/observation", headers={"X-Agent-Id": "someone-else"}).status_code == 403
    obs = client.get(f"/agents/{agent_id}/observation", headers={"X-Agent-Id": agent_id})
    assert obs.status_code == 200

    r = client.post(f"/agents/{agent_id}/actions", json=[{"type": "work"}], headers={"X-Agent-Id": agent_id})
    assert r.json() == {"accepted": 1}
    assert client.post("/admin/end-tick").json()["tick"] == 0
    assert client.get("/world/state").json()["tick"] == 1


def test_world_events_and_cors():
    client = TestClient(create_app(SimulationEngine(SimConfig())))
    client.post("/admin/begin-tick")
    client.post("/admin/end-tick")
    events = client.get("/world/events?since_tick=0").json()
    assert all(e["tick"] >= 0 for e in events)
    r = client.get("/world/state", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
