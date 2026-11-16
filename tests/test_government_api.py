"""政府路徑（lockstep）的測試。格式見 docs/api.md。"""

from dataclasses import replace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from civsim.api.server import create_app
from civsim.config import SocialRuleConfig
from civsim.world import SimulationEngine

RUN = "test-run"
OBS = f"/runs/{RUN}/government/observation"
DEC = f"/runs/{RUN}/government/decisions"
REF = f"/runs/{RUN}/government/reflections"
MEM = f"/runs/{RUN}/government/memory"


@pytest.fixture
def engine(small_config):
    cfg = replace(small_config, social_rules=SocialRuleConfig(path="rules/v0.yaml", mode="enforce"))
    return SimulationEngine(cfg, government=None)


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine, run_id=RUN))


def decide(client, tick, *actions):
    return client.post(DEC, json={"tick": tick, "actions": list(actions)})


def test_list_runs(client, engine):
    [run] = client.get("/runs").json()
    assert run["run_id"] == RUN
    assert run["status"] == "awaiting_decision"
    assert run["tick"] == 0 and run["total_ticks"] == engine.config.total_ticks


def test_observation_does_not_advance_world(client, engine):
    first = client.get(OBS).json()
    second = client.get(OBS).json()
    assert first == second
    assert first["status"] == "awaiting_decision"
    obs = first["observation"]
    assert obs["tick"] == 0 and engine.world.tick == 0
    assert obs["rules"] == ["[禁止] 不能亂殺平民", "[禁止] 不能發行貨幣"]
    assert "food" not in obs["citizens"][0]  # 政府看不到平民的存糧


def test_decision_advances_one_day(client, engine):
    r = decide(client, 0, {"type": "idle"})
    assert r.status_code == 200
    body = r.json()
    assert body["tick"] == 0 and body["next_tick"] == 1 and engine.world.tick == 1
    assert body["status"] == "awaiting_decision"
    assert body["price"] == engine.history[-1]["price"]
    assert client.get(OBS).json()["observation"]["tick"] == 1


def test_empty_actions_means_idle(client, engine):
    body = decide(client, 0).json()
    assert body["decisions"] == [] and engine.world.tick == 1


def test_accepted_decision_has_result(client, engine):
    budget = engine.world.government.budget
    [d] = decide(client, 0, {"type": "import_food", "params": {"qty": 10}, "reason": "補儲備"}).json()["decisions"]
    assert d["accepted"] is True and d["type"] == "import_food" and d["reason"] == "補儲備"
    assert d["result"]["qty"] == 10
    assert engine.world.government.budget < budget


def test_rejected_decision_is_200_and_shown_next_day(client):
    r = decide(client, 0, {"type": "issue_currency", "params": {"amount": 500}})
    assert r.status_code == 200  # 被引擎拒絕不是 HTTP 錯誤
    [d] = r.json()["decisions"]
    assert d["accepted"] is False and "不能發行貨幣" in d["rejected_reason"]
    recent = client.get(OBS).json()["observation"]["recent_decisions"]
    assert recent[-1]["type"] == "issue_currency" and recent[-1]["accepted"] is False


def test_unknown_type_is_rejected_not_http_error(client, engine):
    r = decide(client, 0, {"type": "distribut_food"})
    assert r.status_code == 200 and engine.world.tick == 1
    [d] = r.json()["decisions"]
    assert d["accepted"] is False and "未知的決策類型" in d["rejected_reason"]


def test_tick_mismatch_does_not_advance(client, engine):
    decide(client, 0)
    r = decide(client, 0)  # 例如逾時後重送同一個決策
    assert r.status_code == 409 and r.json()["error"] == "tick_mismatch"
    assert engine.world.tick == 1


def test_unknown_run_is_404(client):
    r = client.get("/runs/nope/government/observation")
    assert r.status_code == 404 and r.json()["error"] == "run_not_found"
    assert client.post("/runs/nope/government/decisions", json={"tick": 0}).status_code == 404


def test_missing_tick_is_422(client, engine):
    assert client.post(DEC, json={"actions": []}).status_code == 422
    assert engine.world.tick == 0


def run_until(client, status, tick=0):
    """每天送 import_food，直到狀態變成 status。回傳最後一個回應。"""
    while True:
        body = decide(client, tick, {"type": "import_food", "params": {"qty": 1}}).json()
        assert len(body["decisions"]) == 1 and body["decisions"][0]["accepted"] is True
        if body["status"] != "awaiting_decision":
            assert body["status"] == status
            return body
        tick = body["next_tick"]


def test_run_to_finish_across_resets(client, engine):
    """跑完整個 run：每天都看得到自己的決策結果，每次天災結束都要反思。"""
    status, tick, reflections = "awaiting_decision", 0, 0
    while status != "finished":
        if status == "awaiting_decision":
            body = decide(client, tick, {"type": "import_food", "params": {"qty": 1}}).json()
            assert len(body["decisions"]) == 1 and body["decisions"][0]["accepted"] is True
        else:
            body = client.post(MEM, json={"memory": f"# v{reflections + 1}"}).json()
            reflections += 1
        status, tick = body["status"], body["next_tick"]
    assert reflections == len(engine.schedule)
    assert engine.memory_versions == ["", "# v1", "# v2"]
    assert engine.world.tick == engine.config.total_ticks
    assert decide(client, engine.world.tick).json()["error"] == "wrong_status"
    assert client.get(OBS).status_code == 409


# ---- 反思 ----
def reach_reflection(client, engine):
    body = run_until(client, "awaiting_reflection")
    assert body["tick"] == engine.schedule[0].window_end
    return body


def test_reflection_pauses_before_reset(client, engine):
    reach_reflection(client, engine)
    d = engine.schedule[0]
    [run] = client.get("/runs").json()
    assert run["status"] == "awaiting_reflection" and run["tick"] == d.window_end
    assert engine.world.government.budget < engine.initial_world.government.budget  # 還沒重置

    data = client.get(REF).json()
    assert data["status"] == "awaiting_reflection" and data["memory"] == ""
    assert data["report"]["disaster_id"] == d.id and data["report"]["window_end"] == d.window_end
    assert len(data["report"]["decisions"]) > 0  # 政府看得到這次天災自己做過的決策


def test_cannot_decide_or_step_while_reflecting(client, engine):
    reach_reflection(client, engine)
    assert client.get(OBS).json()["error"] == "wrong_status"
    assert decide(client, engine.world.tick).json()["error"] == "wrong_status"
    assert client.post("/admin/step").status_code == 409


def test_reflection_paths_only_while_reflecting(client):
    assert client.get(REF).json()["error"] == "wrong_status"
    assert client.post(MEM, json={"memory": "x"}).json()["error"] == "wrong_status"


def test_memory_updates_and_world_resets(client, engine):
    reach_reflection(client, engine)
    d = engine.schedule[0]
    body = client.post(MEM, json={"memory": "# 經驗\n- 進口有用", "reason": "測試"}).json()
    assert body == {"run_id": RUN, "memory_result": "updated", "memory_version": 1,
                    "status": "awaiting_decision", "next_tick": d.window_end + 1}
    assert engine.world.government == engine.initial_world.government  # 已調回均衡狀態
    obs = client.get(OBS).json()["observation"]
    assert obs["memory"] == "# 經驗\n- 進口有用" and obs["recent_decisions"] == []


def test_memory_null_is_unchanged(client, engine):
    reach_reflection(client, engine)
    body = client.post(MEM, json={"memory": None}).json()
    assert body["memory_result"] == "unchanged" and body["memory_version"] == 0


def test_too_long_memory_is_rejected_not_http_error(client, engine):
    reach_reflection(client, engine)
    r = client.post(MEM, json={"memory": "x" * 10_000})
    assert r.status_code == 200 and r.json()["memory_result"] == "rejected"
    assert r.json()["status"] == "awaiting_decision"  # 記憶被拒絕，世界照樣重置
    assert engine.memory == ""


def test_memory_field_is_required(client, engine):
    reach_reflection(client, engine)
    assert client.post(MEM, json={}).status_code == 422  # 不更新要明確送 null


def test_no_memory_group_never_reflects(small_config):
    cfg = replace(small_config, government=replace(small_config.government, memory=False))
    c = TestClient(create_app(SimulationEngine(cfg, government=None), run_id=RUN))
    body = run_until(c, "finished")
    assert body["next_tick"] is None
