import json
from enum import Enum

import pytest

from civsim.agents import LLMGovernment, NoGovernment, make_government
from civsim.agents.government import (
    GOV_PROMPT_VERSION,
    REFLECT_SYSTEM_PROMPT,
    build_prompt,
    build_system_prompt,
    parse_decisions,
    parse_memory,
)
from civsim.agents.llm import ParseError, ScriptedClient
from civsim.world.government import GovernmentActionType, GovernmentDecision, GovernmentObservation

IDLE = '{"actions": [{"type": "idle", "reason": "觀望"}]}'
REPORT = {"disaster_id": 1, "window_end": 20, "goals_met": False}


def make_obs(**overrides) -> GovernmentObservation:
    values = {"tick": 3, "prices": {"food": 5.0}, "memory": "# 政府記憶", "rules": ["不能亂殺平民"]}
    return GovernmentObservation(**{**values, **overrides})


# ---- prompt ----
def test_system_prompt_lists_only_actions_the_engine_supports():
    prompt = build_system_prompt()
    assert "idle" in prompt and "execute_citizen" in prompt
    assert "publish_forecast" not in prompt  # 引擎沒有的決策不能讓政府選


def test_system_prompt_follows_engine_action_list():
    class Actions(str, Enum):
        ISSUE_CURRENCY = "issue_currency"
        NEW_POLICY = "new_policy"

    prompt = build_system_prompt(Actions)
    assert "發行新貨幣" in prompt
    assert "new_policy：參數待補" in prompt


def test_prompt_contains_rules_and_memory():
    prompt = build_prompt(make_obs())
    assert "- 不能亂殺平民" in prompt and "# 政府記憶" in prompt


def test_prompt_state_is_json_and_hides_missing_fields():
    prompt = build_prompt(make_obs(budget=500.0, hungry=3, citizens=[{"id": "c01", "type": "consumer"}]))
    state = json.loads(prompt.split("```json\n")[1].split("\n```")[0])
    assert state["tick"] == 3 and state["budget"] == 500.0 and state["hungry"] == 3
    assert state["citizens"] == [{"id": "c01", "type": "consumer"}]
    assert "price_cap" not in state  # 沒有的資訊不給 LLM


def test_prompt_says_when_there_are_no_rules_or_memory():
    prompt = build_prompt(make_obs(rules=[], memory=None))
    assert "目前沒有社會規則" in prompt and "目前沒有記憶" in prompt


def test_system_prompt_states_goal_and_no_forecast():
    prompt = build_system_prompt()
    assert "均衡" in prompt and "沒有天災預報" in prompt and '{"actions": []}' in prompt


# ---- 解析 ----
def test_parse_decisions_accepts_code_fence_and_extra_text():
    decisions, skipped = parse_decisions(f"好的：\n```json\n{IDLE}\n```")
    assert decisions == [GovernmentDecision(GovernmentActionType.IDLE, {}, "觀望")] and not skipped


def test_parse_decisions_skips_bad_items():
    text = json.dumps({"actions": ["idle", {"type": "fly"}, {"type": "idle", "params": 3}, {"type": "IDLE"}]})
    decisions, skipped = parse_decisions(text)
    assert [d.type for d in decisions] == [GovernmentActionType.IDLE]
    assert len(skipped) == 3


def test_parse_decisions_allows_doing_nothing():
    assert parse_decisions('{"actions": []}') == ([], [])


@pytest.mark.parametrize("text", ["", "not json", '{"actions": "idle"}', '{"actions": [{"type": "fly"}]}'])
def test_parse_decisions_rejects_unusable_response(text):
    with pytest.raises(ParseError):
        parse_decisions(text)


def test_parse_memory():
    assert parse_memory('{"memory": "# 新記憶\\n- 經驗"}') == "# 新記憶\n- 經驗"
    assert parse_memory('{"memory": null}') is None


def test_parse_memory_keeps_code_fence_inside_markdown():
    text = json.dumps({"memory": "# 記憶\n```\n範例\n```\n"}, ensure_ascii=False)
    assert "範例" in parse_memory(text)


@pytest.mark.parametrize("text", ["沒有 JSON", '{"reason": "x"}', '{"memory": 3}'])
def test_parse_memory_rejects_bad_response(text):
    with pytest.raises(ParseError):
        parse_memory(text)


# ---- 決策 ----
def test_decide_uses_llm_and_records_call():
    gov = LLMGovernment(ScriptedClient([IDLE]))
    assert [d.type for d in gov.decide(make_obs())] == [GovernmentActionType.IDLE]
    call = gov.calls[-1]
    assert call.tick == 3 and call.trigger == "decide" and call.response == IDLE
    assert call.model == "scripted" and call.prompt_version == GOV_PROMPT_VERSION
    assert not call.used_fallback and not call.error


def test_decide_sends_system_prompt_and_observation():
    seen = {}

    def respond(system, user):
        seen.update(system=system, user=user)
        return IDLE

    LLMGovernment(ScriptedClient(respond)).decide(make_obs())
    assert seen["system"] == build_system_prompt()
    assert seen["user"] == build_prompt(make_obs())


def test_decide_limits_decisions_per_day():
    text = json.dumps({"actions": [{"type": "idle"}] * 4})
    gov = LLMGovernment(ScriptedClient([text]), max_decisions=2)
    assert len(gov.decide(make_obs())) == 2
    assert "截掉 2 個" in gov.calls[-1].skipped[0]


def test_decide_records_token_usage():
    client = ScriptedClient([IDLE], last_usage={"total_tokens": 42})
    gov = LLMGovernment(client)
    gov.decide(make_obs())
    assert gov.calls[-1].usage == {"total_tokens": 42}


@pytest.mark.parametrize("respond", [["沒有 JSON"], ['{"actions": 3}']])
def test_decide_falls_back_on_bad_response(respond):
    gov = LLMGovernment(ScriptedClient(respond))
    assert gov.decide(make_obs()) == []
    assert gov.calls[-1].used_fallback and gov.calls[-1].error


def test_decide_falls_back_on_client_error():
    def boom(system, user):
        raise TimeoutError("連線逾時")

    class Fallback(NoGovernment):
        def decide(self, obs):
            return [GovernmentDecision(GovernmentActionType.IDLE, {}, "fallback")]

    gov = LLMGovernment(ScriptedClient(boom), fallback=Fallback())
    assert gov.decide(make_obs())[0].reason == "fallback"
    assert "TimeoutError" in gov.calls[-1].error


# ---- 反思 ----
def test_reflect_returns_new_memory_and_records_call():
    def respond(system, user):
        assert system == REFLECT_SYSTEM_PROMPT
        data = json.loads(user)
        assert data["report"] == REPORT and data["current_memory"] == "舊記憶"
        return '{"memory": "新記憶", "reason": "第 1 次天災的教訓"}'

    gov = LLMGovernment(ScriptedClient(respond))
    assert gov.reflect(REPORT, "舊記憶") == "新記憶"
    assert gov.calls[-1].tick == 20 and gov.calls[-1].trigger == "reflect"


def test_reflect_can_choose_not_to_change():
    assert LLMGovernment(ScriptedClient(['{"memory": null}'])).reflect(REPORT, "舊記憶") is None


def test_reflect_failure_keeps_memory():
    gov = LLMGovernment(ScriptedClient(["不是 JSON"]))
    assert gov.reflect(REPORT, "舊記憶") is None
    assert gov.calls[-1].error


# ---- 建立 ----
def test_no_government_never_acts():
    assert NoGovernment().decide(make_obs()) == []
    assert NoGovernment().reflect(REPORT, "舊記憶") is None


def test_make_government_without_provider_fails_loudly(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(ValueError):
        make_government()


# ---- 沒變化就不呼叫（call_policy="on_change"）----
def counting_government(**options):
    seen = []

    def respond(system, user):
        seen.append(user)
        return IDLE
    return LLMGovernment(ScriptedClient(respond), call_policy="on_change", **options), seen


def test_on_change_skips_when_nothing_changed_and_reuses_decision():
    gov, seen = counting_government()
    first = gov.decide(make_obs(tick=1, hungry=3))
    again = gov.decide(make_obs(tick=2, prices={"food": 5.1}, hungry=4))  # 價格差 2%、挨餓多 1 人
    assert len(seen) == 1 and again == first
    assert not gov.calls[-1].used_llm and "第 1 天" in gov.calls[-1].trigger


@pytest.mark.parametrize("change", [
    {"prices": {"food": 6.0}},  # 價格變 20%
    {"hungry": 10},  # 挨餓多很多
    {"deaths": 1},
    {"memory": "# 新記憶"},
    {"recent_decisions": [{"tick": 1, "type": "idle", "params": {}, "accepted": False}]},  # 昨天被拒絕
])
def test_on_change_calls_when_something_changed(change):
    gov, seen = counting_government()
    gov.decide(make_obs(tick=1, hungry=3))
    gov.decide(make_obs(**{"tick": 2, "hungry": 3, **change}))
    assert len(seen) == 2


def test_on_change_calls_at_least_every_max_skip_days():
    gov, seen = counting_government(max_skip_days=2)
    for tick in range(1, 8):
        gov.decide(make_obs(tick=tick))
    assert len(seen) == 3  # 第 1、4、7 天


def test_on_change_calls_again_after_reflection_and_failure():
    gov, seen = counting_government()
    gov.decide(make_obs(tick=1))
    gov.reflect(REPORT, "舊記憶")  # 回應不是 memory，反思失敗也一樣要重新呼叫
    gov.decide(make_obs(tick=2))
    assert sum("current_memory" not in u for u in seen) == 2


def test_always_policy_calls_every_day():
    gov = LLMGovernment(ScriptedClient([IDLE, IDLE]))
    gov.decide(make_obs(tick=1))
    gov.decide(make_obs(tick=2))
    assert all(c.used_llm for c in gov.calls)


def test_unknown_call_policy_fails():
    with pytest.raises(ValueError):
        LLMGovernment(ScriptedClient([]), call_policy="sometimes")
