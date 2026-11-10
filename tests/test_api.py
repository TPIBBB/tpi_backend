import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from civsim.api.server import create_app
from civsim.world import SimulationEngine


def test_step_and_world_state(small_config):
    client = TestClient(create_app(SimulationEngine(small_config, government=None)))
    assert client.post("/admin/step").json()["tick"] == 0
    state = client.get("/world/state").json()
    assert state["tick"] == 1 and state["band"]["low"] < state["band"]["high"]
    assert len(state["citizens"]) == small_config.n_citizens
    assert all(e["tick"] >= 0 for e in client.get("/world/events?since_tick=0").json())


def test_cors(small_config):
    client = TestClient(create_app(SimulationEngine(small_config, government=None)))
    r = client.get("/world/state", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_government_api_skeleton_imports():
    import importlib

    importlib.import_module("civsim.api.government")
