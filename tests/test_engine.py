from dataclasses import replace

from civsim.config import SimConfig, InstitutionConfig
from civsim.models import Action, ActionType
from civsim.world import SimulationEngine


def test_run_is_reproducible():
    a = SimulationEngine(SimConfig(ticks=10)).run()
    b = SimulationEngine(SimConfig(ticks=10)).run()
    assert a == b


def test_agent_cannot_buy_without_money():
    engine = SimulationEngine(SimConfig())
    agent = next(iter(engine.world.agents.values()))
    agent.inventory["money"] = 0
    engine.begin_tick()
    events = engine.step({agent.id: [Action(agent.id, ActionType.TRADE, {"side": "buy", "good": "food", "qty": 1})]})
    trade = [e for e in events if e.actor == agent.id and e.kind == "action:trade"]
    assert trade and not trade[0].success


def test_hierarchical_hides_prices_from_non_elite():
    config = replace(SimConfig(), institution=InstitutionConfig(preset="hierarchical"))
    engine = SimulationEngine(config)
    elites = engine.policy.authorities()
    commoner = next(a for a in engine.world.agents if a not in elites)
    assert engine.observe(commoner).prices is None
    assert engine.observe(next(iter(elites))).prices is not None


def test_cannot_grant_without_authority():
    engine = SimulationEngine(SimConfig())  # equal：沒有人有授權能力
    a, b = list(engine.world.agents)[:2]
    engine.begin_tick()
    events = engine.step({a: [Action(a, ActionType.GRANT_PERMISSION, {"permission": "read:prices", "target": b})]})
    grant = [e for e in events if e.kind == "action:grant_permission"]
    assert grant and not grant[0].success
