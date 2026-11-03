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
    assert "idle" in prompt
    assert "execute_citizen" not in prompt  # 引擎還沒實作的決策不能讓政府選


def test_system_prompt_follows_engine_action_list():
    class Actions(str, Enum):
        ISSUE_CURRENCY = "issue_currency"
        NEW_POLICY = "new_policy"

    prompt = build_system_prompt(Actions)
    assert "發行新貨幣" in prompt
    assert "new_policy：參數待補" in prompt


def test_prompt_contains_rules_and_memory():
    data = json.loads(build_prompt(make_obs()))
    assert data["rules"] == ["不能亂殺平民"] and data["memory"] == "# 政府記憶"


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
    assert json.loads(seen["user"])["tick"] == 3


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
