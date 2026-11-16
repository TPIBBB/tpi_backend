import pytest

from civsim.world.government import GovernmentActionType as T
from civsim.world.government import GovernmentDecision
from civsim.world.social_rules import SocialRule, find_violations, load_rules

RULES = [
    SocialRule("no_execution", "不能亂殺平民", forbids=["execute_citizen"]),
    SocialRule("currency_limit", "單次發行不得超過 200", action="issue_currency", param="amount", max=200),
    SocialRule("care", "要照顧弱勢", kind="do"),
]


def test_kind_rule():
    assert [r.id for r in find_violations(GovernmentDecision(T.EXECUTE_CITIZEN, {"target": "c00"}), RULES)] == [
        "no_execution"]


@pytest.mark.parametrize("amount,violates", [(200, False), (201, True), ("lots", False)])
def test_degree_rule(amount, violates):
    v = find_violations(GovernmentDecision(T.ISSUE_CURRENCY, {"amount": amount}), RULES)
    assert bool(v) == violates


def test_do_rules_are_not_checked():
    assert find_violations(GovernmentDecision(T.IDLE), RULES) == []


def test_load_v0_rules():
    rules = load_rules("rules/v0.yaml")
    assert rules.version == "v0" and {r.id for r in rules.rules} == {"no_execution", "no_currency"}
    assert find_violations(GovernmentDecision(T.ISSUE_CURRENCY, {"amount": 1}), rules.rules)


def test_load_rejects_unknown_action(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("rules:\n  - {id: x, text: x, forbids: [fly]}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_rules(path)
