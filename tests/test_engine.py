import json
from dataclasses import replace

import pytest

from civsim.agents import LLMGovernment
from civsim.agents.llm import ScriptedClient
from civsim.analysis.goals import evaluate_disaster, first_sustained
from civsim.config import DisasterConfig, SocialRuleConfig
from civsim.world import SimulationEngine
from civsim.world.disasters import build_schedule
from civsim.world.equilibrium import band_from_prices
from civsim.world.government import GovernmentActionType as T
from civsim.world.government import GovernmentDecision


def test_run_is_reproducible(small_config):
    a = SimulationEngine(small_config, government=None).run()
    b = SimulationEngine(small_config, government=None).run()
    assert a == b and len(a) == small_config.total_ticks


def test_schedule_phases():
    s = build_schedule(DisasterConfig(count=2, stable_days=3, stable_jitter=0, disaster_days=2, evaluation_days=4))
    assert [(d.cycle_start, d.start_tick, d.end_tick, d.window_end) for d in s] == [(0, 3, 4, 8), (9, 12, 13, 17)]
    assert [s[0].phase_of(t) for t in (0, 3, 5, 9)] == ["stable", "disaster", "evaluation", None]


def test_stable_length_varies_but_window_is_fixed():
    cfg = DisasterConfig(count=8, stable_days=20, stable_jitter=5, disaster_days=5, evaluation_days=15)
    s = build_schedule(cfg)
    stables = [d.start_tick - d.cycle_start for d in s]
    assert len(set(stables)) > 1 and all(15 <= x <= 25 for x in stables)
    assert all(d.window_end - d.end_tick == 15 and d.end_tick - d.start_tick == 4 for d in s)
    assert all(b.cycle_start == a.window_end + 1 for a, b in zip(s, s[1:]))


def test_government_cannot_see_day_in_cycle(small_config):
    obs = SimulationEngine(small_config, government=None).government_observation()
    assert not hasattr(obs, "day")


def test_schedule_jitter_depends_only_on_schedule_seed():
    cfg = DisasterConfig(multiplier_jitter=0.1)
    assert build_schedule(cfg) == build_schedule(cfg)
    assert build_schedule(cfg) != build_schedule(replace(cfg, schedule_seed=1))


def test_disaster_cuts_harvest(small_config):
    engine = SimulationEngine(small_config, government=None)
    phases = {}
    for _ in range(small_config.disasters.stable_days + 1):
        engine.step()
        phases[engine.history[-1]["phase"]] = engine.history[-1]["food_multiplier"]
    assert phases == {"stable": 1.0, "disaster": small_config.disasters.food_multiplier}


def test_band_is_same_for_every_government(small_config):
    a = SimulationEngine(small_config, government=None).band
    b = SimulationEngine(replace(small_config, social_rules=SocialRuleConfig(mode="off")), government=None).band
    assert a == b and a.low < a.mean < a.high


def test_band_min_width():
    band = band_from_prices([5.0, 5.0, 5.0], k=2.5, min_half_width=0.02)
    assert band.low == pytest.approx(4.9) and band.high == pytest.approx(5.1)


def test_reset_restores_initial_world_but_keeps_tick(small_config):
    gov = LLMGovernment(ScriptedClient(lambda s, u: json.dumps(
        {"actions": [{"type": "execute_citizen", "params": {"target": "c00"}}]})))
    cfg = replace(small_config, social_rules=SocialRuleConfig(mode="off"))
    engine = SimulationEngine(cfg, government=gov)
    window_end = engine.schedule[0].window_end
    for _ in range(window_end + 1):
        engine.step()
    assert engine.history[window_end]["deaths"] == 1
    assert engine.world.tick == window_end + 1
    assert engine.world.citizens["c00"].alive and engine.world.deaths == 0
    assert engine.world.government == engine.initial_world.government


def scripted_government(decisions: list[dict], memory: str | None = "# 記憶 v1"):
    def respond(system, user):
        if "current_memory" in user:
            return json.dumps({"memory": memory})
        return json.dumps({"actions": decisions})
    return LLMGovernment(ScriptedClient(respond))


def test_rules_enforced_and_reason_shown_next_day(small_config):
    cfg = replace(small_config, social_rules=SocialRuleConfig(path="rules/v0.yaml", mode="enforce"))
    engine = SimulationEngine(cfg, government=scripted_government(
        [{"type": "execute_citizen", "params": {"target": "c00"}}]))
    events = engine.step()
    assert any(e.kind == "gov:rejected" and "不能亂殺平民" in e.message for e in events)
    assert engine.world.citizens["c00"].alive
    obs = engine.government_observation()
    assert obs.recent_decisions[-1]["accepted"] is False and obs.rules


def test_record_mode_executes_but_logs_violation(small_config):
    cfg = replace(small_config, social_rules=SocialRuleConfig(path="rules/v0.yaml", mode="record"))
    engine = SimulationEngine(cfg, government=scripted_government(
        [{"type": "execute_citizen", "params": {"target": "c00"}}]))
    events = engine.step()
    assert any(e.kind == "rule:violation" for e in events)
    assert not engine.world.citizens["c00"].alive
    assert engine.government_observation().rules == []  # B 組看不到規則


def test_reflection_updates_memory_and_report(small_config):
    engine = SimulationEngine(small_config, government=scripted_government([]))
    engine.run()
    assert len(engine.reports) == small_config.disasters.count
    assert engine.memory == "# 記憶 v1" and len(engine.memory_versions) == 3
    assert engine.reports[1]["memory_version"] == 1


def test_no_memory_group_never_reflects(small_config):
    cfg = replace(small_config, government=replace(small_config.government, memory=False))
    engine = SimulationEngine(cfg, government=scripted_government([]))
    engine.run()
    assert engine.memory_versions == [""]
    assert engine.government_observation().memory is None


def test_too_long_memory_is_rejected(small_config):
    engine = SimulationEngine(small_config, government=scripted_government([], memory="x" * 10_000))
    engine.run()
    assert engine.memory_versions == [""]


def test_api_mode_accepts_external_decisions(small_config):
    engine = SimulationEngine(small_config, government=None)
    engine.begin_tick()
    obs = engine.government_observation()
    assert obs.budget == small_config.government.budget and obs.population == small_config.n_citizens
    events = engine.step([GovernmentDecision(T.CASH_TRANSFER, {"per_person": 1})])
    assert any(e.kind == "gov:cash_transfer" for e in events)


def test_evaluate_requires_staying_in_band():
    d = build_schedule(DisasterConfig(count=1, stable_days=1, stable_jitter=0, disaster_days=1, evaluation_days=4))[0]
    band = band_from_prices([4.0, 6.0], k=1)  # 4 ~ 6

    def history(prices, capped=()):
        return [{"tick": t, "price": p, "price_capped": t in capped, "hungry": 0, "deaths": 0}
                for t, p in enumerate(prices)]

    ok = evaluate_disaster(d, history([5, 9, 8, 5, 5, 5]), band)
    assert ok["success"] and ok["recovered_day"] == 2
    left = evaluate_disaster(d, history([5, 9, 5, 9, 5, 5]), band)
    assert not left["success"] and left["left_band_after_recovery"]
    capped = evaluate_disaster(d, history([5, 9, 5, 5, 5, 5], capped={5}), band)
    assert not capped["success"]
    assert first_sustained([{"disaster_id": i, "success": s} for i, s in enumerate([True, False, True, True], 1)]) == 3


def test_government_gets_one_decision_per_day(small_config):
    engine = SimulationEngine(small_config, government=scripted_government([
        {"type": "cash_transfer", "params": {"per_person": 1}},
        {"type": "cash_transfer", "params": {"per_person": 1}},
    ]))
    budget = engine.world.government.budget
    events = engine.step()
    assert engine.world.government.budget == budget - small_config.n_citizens  # 只執行第一個
    rejected = [e for e in events if e.kind == "gov:rejected"]
    assert len(rejected) == 1 and "決策上限 1" in rejected[0].message
    assert engine.government_observation().recent_decisions[-1]["accepted"] is False
