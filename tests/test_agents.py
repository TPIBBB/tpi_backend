import json
import random
from dataclasses import replace

import pytest

from civsim.agents import build_controllers
from civsim.agents.llm import (
    LLMAgent,
    ParseError,
    ScriptedClient,
    build_prompt,
    parse_actions,
    summarize_memory,
)
from civsim.agents.rule_based import RuleBasedAgent
from civsim.config import InstitutionConfig, SimConfig
from civsim.models import ActionType, PermissionRequest
from civsim.world import SimulationEngine
from civsim.world.events import FORECAST_FOOD


def make_engine(**overrides) -> SimulationEngine:
    return SimulationEngine(replace(SimConfig(), **overrides))


def agent_of_role(engine: SimulationEngine, role: str) -> str:
    return next(a.id for a in engine.world.agents.values() if a.role == role)


def add_forecast(engine: SimulationEngine) -> None:
    engine.world.forecasts[FORECAST_FOOD] = {"tick": engine.world.tick + 1, "food_multiplier": 0.4}


# ---- 規則式 Agent ----
def test_rule_based_respects_action_points():
    engine = make_engine()
    for agent_id, controller in engine.controllers.items():
        actions = controller.decide(engine.observe(agent_id))
        assert len(actions) <= engine.world.agents[agent_id].action_points


def test_merchant_without_prices_only_works():
    engine = make_engine(institution=InstitutionConfig(preset="none"))
    merchant = agent_of_role(engine, "merchant")
    actions = engine.controllers[merchant].decide(engine.observe(merchant))
    assert all(a.type != ActionType.TRADE for a in actions)
    assert any(a.type == ActionType.WORK for a in actions)


def test_merchant_speculates_on_food_forecast():
    engine = make_engine()
    merchant = agent_of_role(engine, "merchant")
    me = engine.world.agents[merchant]
    me.persona = replace(me.persona, greed=1.0, risk_tolerance=0.0)
    add_forecast(engine)
    actions = engine.controllers[merchant].decide(engine.observe(merchant))
    assert any(a.type == ActionType.TRADE and a.params["side"] == "buy" and a.params["good"] == "food"
               for a in actions)


def test_farmer_hoards_on_food_forecast():
    engine = make_engine()
    farmer = agent_of_role(engine, "farmer")
    me = engine.world.agents[farmer]
    me.persona = replace(me.persona, greed=1.0, sociability=0.0)
    me.inventory["food"] = 50
    add_forecast(engine)
    actions = engine.controllers[farmer].decide(engine.observe(farmer))
    assert not any(a.type == ActionType.TRADE and a.params["side"] == "sell" for a in actions)


def test_craftsman_does_not_work_without_wood():
    engine = make_engine()
    craftsman = agent_of_role(engine, "craftsman")
    engine.world.agents[craftsman].inventory["wood"] = 0
    actions = engine.controllers[craftsman].decide(engine.observe(craftsman))
    assert not any(a.type == ActionType.WORK for a in actions)


def test_citizen_buys_what_it_can_afford_when_low_on_money():
    """錢不夠買足時要買得起多少買多少，否則整筆被拒絕，有錢也會餓死。"""
    engine = make_engine()
    agent_id = agent_of_role(engine, "woodcutter")
    me = engine.world.agents[agent_id]
    me.inventory.update(food=0, money=engine.world.market.prices["food"] * 2.5)
    actions = RuleBasedAgent(agent_id, random.Random(0)).decide(engine.observe(agent_id))
    buys = [a for a in actions if a.type == ActionType.TRADE and a.params["side"] == "buy"]
    assert buys[0].params["qty"] == 2


def test_permission_requests_rotate_targets():
    engine = make_engine(institution=InstitutionConfig(preset="none"))
    agent_id = agent_of_role(engine, "merchant")
    controller = RuleBasedAgent(agent_id, random.Random(0))
    targets = []
    for _ in range(5):
        obs = engine.observe(agent_id)
        obs.self_state.action_points = 5
        targets += [a.params["target"] for a in controller.decide(obs)
                    if a.type == ActionType.REQUEST_PERMISSION]
    assert len(targets) == 5 and len(set(targets)) == 5


# ---- LLM 回應解析 ----
def test_parse_actions_accepts_code_fence_and_extra_text():
    text = '好的，以下是我的決定：\n```json\n{"actions": [{"type": "WORK", "reason": "上工"}]}\n```'
    actions, skipped = parse_actions("a00", text)
    assert [a.type for a in actions] == [ActionType.WORK] and not skipped


def test_parse_actions_skips_bad_items_and_truncates():
    text = json.dumps({"actions": [
        {"type": "fly"},
        "work",
        {"type": "work"},
        {"type": "trade", "params": {"side": "buy", "good": "food", "qty": 1}},
        {"type": "idle"},
    ]})
    actions, skipped = parse_actions("a00", text, max_actions=2)
    assert [a.type for a in actions] == [ActionType.WORK, ActionType.TRADE]
    assert len(skipped) == 3


@pytest.mark.parametrize("text", ["", "not json", '{"actions": "work"}', '{"actions": [{"type": "fly"}]}'])
def test_parse_actions_rejects_unusable_response(text):
    with pytest.raises(ParseError):
        parse_actions("a00", text)


def test_summarize_memory_keeps_recent_and_counts_older():
    memory = [f"t{i}: a01 告訴我 forecast:food" for i in range(8)] + ["t8: a02 授予我 read:prices"]
    summary = summarize_memory(memory, recent=2)
    assert summary["recent"] == memory[-2:]
    assert summary["earlier_total"] == 7
    assert summary["earlier_summary"] == ["a01 告訴我 forecast:food（7 次）"]


def test_prompt_marks_hidden_prices():
    engine = make_engine(institution=InstitutionConfig(preset="none"))
    prompt = json.loads(build_prompt(engine.observe("a00")))
    assert isinstance(prompt["prices"], str)


# ---- LLM Agent ----
def make_llm_agent(engine, agent_id, client, call_policy="always"):
    return LLMAgent(agent_id, RuleBasedAgent(agent_id, random.Random(0)), client, call_policy)


def test_llm_agent_uses_llm_actions():
    engine = make_engine()
    client = ScriptedClient(['{"actions": [{"type": "idle", "reason": "休息"}]}'])
    agent = make_llm_agent(engine, "a00", client)
    actions = agent.decide(engine.observe("a00"))
    assert [a.type for a in actions] == [ActionType.IDLE]
    assert agent.calls[-1].used_llm and not agent.calls[-1].used_fallback


@pytest.mark.parametrize("respond", [["沒有 JSON"], ['{"actions": 3}']])
def test_llm_agent_falls_back_on_bad_response(respond):
    engine = make_engine()
    agent = make_llm_agent(engine, "a00", ScriptedClient(respond))
    actions = agent.decide(engine.observe("a00"))
    assert actions and agent.calls[-1].used_fallback and agent.calls[-1].error


def test_llm_agent_falls_back_on_client_error():
    def boom(system, user):
        raise TimeoutError("連線逾時")

    engine = make_engine()
    agent = make_llm_agent(engine, "a00", ScriptedClient(boom))
    assert agent.decide(engine.observe("a00"))
    assert "TimeoutError" in agent.calls[-1].error


def test_on_event_policy_calls_llm_only_when_something_happens():
    engine = make_engine()
    client = ScriptedClient(lambda s, u: '{"actions": [{"type": "idle"}]}')
    agent = make_llm_agent(engine, "a00", client, call_policy="on_event")

    engine.world.tick = 1
    agent.decide(engine.observe("a00"))
    assert not agent.calls[-1].used_llm

    add_forecast(engine)
    agent.decide(engine.observe("a00"))
    assert agent.calls[-1].used_llm and "forecast" in agent.calls[-1].trigger

    engine.world.forecasts.clear()
    engine.world.agents["a00"].known_info.clear()
    engine.world.pending_requests.append(PermissionRequest(1, "a01", "a00", "read:prices"))
    agent.decide(engine.observe("a00"))
    assert agent.calls[-1].trigger == "pending_requests"


def test_llm_mode_without_provider_matches_rule_based(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    rule = SimulationEngine(replace(SimConfig(), ticks=10)).run()
    llm = SimulationEngine(replace(SimConfig(), ticks=10, agent_controller="llm")).run()
    assert rule == llm


def test_build_controllers_rejects_unknown_call_policy(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    engine = make_engine()
    config = replace(SimConfig(), agent_controller="llm", llm_call_policy="sometimes")
    with pytest.raises(ValueError):
        build_controllers(engine.world, config)
