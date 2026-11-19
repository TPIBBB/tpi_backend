import json
from dataclasses import replace

import pytest

from civsim.agents import LLMGovernment
from civsim.agents.llm import ScriptedClient
from civsim.analysis.goals import evaluate_disaster, first_sustained
from civsim.config import DisasterConfig, SocialRuleConfig
from civsim.world import SimulationEngine
from civsim.world.disasters import build_schedule
from civsim.world.equilibrium import band_from_prices, calibrate, counts_in_band, is_market_price
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


def fake_calibration_run(monkeypatch, rows: list[dict]):
    """讓校準期的模擬直接回傳指定的每日紀錄。"""
    monkeypatch.setattr(SimulationEngine, "run", lambda self, ticks=None: rows)


def test_calibration_ignores_burn_in_and_days_without_trade(small_config, monkeypatch):
    eq = small_config.equilibrium
    burn_in = [{"price": 100.0, "traded": True, "price_capped": False}] * eq.burn_in_days
    stable = [
        {"price": 5.0, "traded": True, "price_capped": False} if i % 2 == 0
        else {"price": 50.0, "traded": False, "price_capped": False}  # 沒成交：價格不算數
        for i in range(eq.calibration_days - eq.burn_in_days)
    ]
    fake_calibration_run(monkeypatch, burn_in + stable)

    band, prices = calibrate(small_config)

    assert band.mean == pytest.approx(5.0)
    assert band.samples == len(stable) // 2
    assert len(prices) == eq.calibration_days  # 回傳的仍是完整校準期的每日價格


def test_calibration_fails_with_too_few_traded_days(small_config, monkeypatch):
    eq = small_config.equilibrium
    rows = [{"price": 5.0, "traded": False, "price_capped": False}] * eq.calibration_days
    rows[-1] = {"price": 5.0, "traded": True, "price_capped": False}
    fake_calibration_run(monkeypatch, rows)

    with pytest.raises(ValueError, match="有效成交資料不足"):
        calibrate(small_config)


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

    def history(prices, capped=(), no_trade=()):
        return [{"tick": t, "price": p, "price_capped": t in capped, "traded": t not in no_trade,
                 "hungry": 0, "deaths": 0}
                for t, p in enumerate(prices)]

    ok = evaluate_disaster(d, history([5, 9, 8, 5, 5, 5]), band)
    assert ok["success"] and ok["recovered_day"] == 2 and ok["no_trade_days"] == 0
    left = evaluate_disaster(d, history([5, 9, 5, 9, 5, 5]), band)
    assert not left["success"] and left["left_band_after_recovery"]
    capped = evaluate_disaster(d, history([5, 9, 5, 5, 5, 5], capped={5}), band)
    assert not capped["success"]

    # 沒成交的日子：價格看起來在區間內也不算
    gap = evaluate_disaster(d, history([5, 9, 5, 5, 5, 5], no_trade={4}), band)
    assert not gap["success"] and gap["left_band_after_recovery"] and gap["no_trade_days"] == 1
    # 沒成交的日子不算回到區間：第一次有成交又在區間內的日子才是 recovered_day
    late = evaluate_disaster(d, history([5, 9, 5, 5, 5, 5], no_trade={2}), band)
    assert late["success"] and late["recovered_day"] == 2
    assert first_sustained([{"disaster_id": i, "success": s} for i, s in enumerate([True, False, True, True], 1)]) == 3


def test_counts_in_band_rules():
    band = band_from_prices([4.0, 6.0], k=1)  # 4 ~ 6

    def day(price=5.0, traded=True, capped=False):
        return {"price": price, "traded": traded, "price_capped": capped}

    assert is_market_price(day()) and counts_in_band(band, day())
    assert not counts_in_band(band, day(price=9.0))  # 區間外
    assert not is_market_price(day(traded=False)) and not counts_in_band(band, day(traded=False))
    assert not is_market_price(day(capped=True)) and not counts_in_band(band, day(capped=True))
    assert not counts_in_band(band, day(traded=False, capped=True))


def test_daily_in_band_matches_disaster_report(small_config, monkeypatch):
    """每日指標的 in_band 和天災報告用同一個判斷：沒成交的日子兩邊都不算在區間內。"""
    import civsim.world.engine as engine_module

    wide = band_from_prices([0.0, 1000.0], k=1)  # 寬到每天的價格都在區間內
    d = build_schedule(small_config.disasters)[0]
    no_trade_tick = d.end_tick + 2  # 第一次天災評估期的第 2 天
    real_settle = engine_module.settle_market

    def settle(world, rng):
        clearing, events = real_settle(world, rng)
        if world.tick == no_trade_tick:
            clearing = replace(clearing, traded=False)
        return clearing, events

    monkeypatch.setattr(engine_module, "settle_market", settle)
    engine = SimulationEngine(small_config, government=None, band=wide)
    history = engine.run()

    assert all(m["in_band"] == counts_in_band(wide, m) for m in history)
    assert [m["tick"] for m in history if not m["in_band"]] == [no_trade_tick]
    first = engine.reports[0]
    assert not first["success"] and first["left_band_after_recovery"] and first["no_trade_days"] == 1


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


def test_citizen_can_harvest_then_sell_the_same_day(small_config):
    from civsim.models import Action, ActionType, CitizenType

    engine = SimulationEngine(small_config, government=None, band=None)
    farmer = next(c for c in engine.world.citizens.values() if c.type == CitizenType.PRODUCER_TRADER)
    farmer.food = 0.0  # 沒收成就沒有糧可以賣

    class HarvestAndSell:
        def decide(self, obs):
            return [Action(farmer.id, ActionType.SELL, {"qty": 3, "price": 0}),
                    Action(farmer.id, ActionType.HARVEST, {}),
                    Action(farmer.id, ActionType.WORK, {})]  # 第二個生產動作會被拒絕

    engine.citizens[farmer.id] = HarvestAndSell()
    events = [e for e in engine.step() if e.actor == farmer.id]
    by_type = {e.kind: e for e in events}
    assert by_type["action:harvest"].success and by_type["action:sell"].success  # 先收成，所以賣得出去
    assert not by_type["action:extra"].success and by_type["action:extra"].payload["dropped"] == ["work"]


def test_failed_reflection_is_logged_separately(small_config):
    def respond(system, user):
        if "current_memory" in user:
            raise TimeoutError("連線逾時")
        return json.dumps({"actions": []})

    engine = SimulationEngine(small_config, government=LLMGovernment(ScriptedClient(respond)))
    kinds = [e.kind for _ in range(small_config.total_ticks) for e in engine.step()]
    assert kinds.count("gov:memory_failed") == small_config.disasters.count
    assert "gov:memory_unchanged" not in kinds and engine.memory_versions == [""]


def test_llm_calls_are_written_to_llm_calls_jsonl(small_config, tmp_path):
    from civsim.storage import JsonlRecorder

    gov = scripted_government([{"type": "idle", "reason": "觀望"}])
    engine = SimulationEngine(small_config, government=gov, recorder=JsonlRecorder(tmp_path))
    engine.run()
    rows = [json.loads(line) for line in (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(gov.calls) == small_config.total_ticks + small_config.disasters.count
    assert {r["trigger"] for r in rows} == {"decide", "reflect"}
    assert all(r["prompt"] and r["response"] for r in rows)
