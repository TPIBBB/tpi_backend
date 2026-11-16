import random

import pytest

from civsim.config import GovernmentConfig, SimConfig
from civsim.models import CitizenType
from civsim.world.government import GovernmentActionType as T
from civsim.world.government import GovernmentDecision, settle, validate
from civsim.world.setup import create_world

CFG = GovernmentConfig()


@pytest.fixture
def world():
    return create_world(SimConfig(), random.Random(0))


def d(type_, **params):
    return GovernmentDecision(type_, params)


@pytest.mark.parametrize("decision", [
    d(T.DISTRIBUTE_FOOD, qty_per_person="many"),
    d(T.DISTRIBUTE_FOOD, qty_per_person=-1),
    d(T.DISTRIBUTE_FOOD, qty_per_person=float("nan")),
    d(T.COLLECT_TAX, rate=1.5),
    d(T.SEIZE_FOOD, rate=0.5, target_type="aliens"),
    d(T.PRICE_CAP, price=5, duration=2.5),
    d(T.PRICE_CAP, good="wood", price=5, duration=2),
    d(T.IMPORT_FOOD, qty=CFG.max_import_per_day + 1),
    d(T.EXECUTE_CITIZEN, target="nobody"),
    d(T.ISSUE_CURRENCY),
])
def test_rejects_bad_params(world, decision):
    assert validate(world, decision, CFG) is not None


def test_distribute_food_checks_and_uses_reserve(world):
    n = len(world.living())
    world.government.food_reserve = n * 2 - 1
    assert "儲備不足" in validate(world, d(T.DISTRIBUTE_FOOD, qty_per_person=2), CFG)
    world.government.food_reserve = n * 2
    assert validate(world, d(T.DISTRIBUTE_FOOD, qty_per_person=2), CFG) is None
    settle(world, d(T.DISTRIBUTE_FOOD, qty_per_person=2), CFG)
    assert world.government.food_reserve == pytest.approx(0)


def test_only_hungry_targets_hungry_citizens(world):
    hungry = next(iter(world.citizens.values()))
    hungry.hungry_days = 1
    food = hungry.food
    event = settle(world, d(T.DISTRIBUTE_FOOD, qty_per_person=3, only_hungry=True), CFG)
    assert event.payload["recipients"] == 1 and hungry.food == food + 3


def test_cash_transfer_and_tax(world):
    budget = world.government.budget
    settle(world, d(T.CASH_TRANSFER, per_person=1), CFG)
    assert world.government.budget == pytest.approx(budget - len(world.living()))
    money = sum(c.money for c in world.living())
    settle(world, d(T.COLLECT_TAX, rate=0.1), CFG)
    assert sum(c.money for c in world.living()) == pytest.approx(money * 0.9)


def test_issue_currency_raises_customary_price(world):
    before = world.market.customary_price
    settle(world, d(T.ISSUE_CURRENCY, amount=world.market.initial_money), CFG)
    assert world.market.customary_price == pytest.approx(before * 2)


def test_seize_food_by_type(world):
    selfs = [c for c in world.living() if c.type == CitizenType.PRODUCER_SELF]
    total = sum(c.food for c in selfs)
    reserve = world.government.food_reserve
    settle(world, d(T.SEIZE_FOOD, rate=0.5, target_type="producer_self"), CFG)
    assert world.government.food_reserve == pytest.approx(reserve + total / 2)


def test_execute_citizen(world):
    target = next(iter(world.citizens))
    settle(world, d(T.EXECUTE_CITIZEN, target=target), CFG)
    assert not world.citizens[target].alive and world.deaths == 1
    assert validate(world, d(T.EXECUTE_CITIZEN, target=target), CFG) is not None


def test_import_costs_premium(world):
    budget = world.government.budget
    settle(world, d(T.IMPORT_FOOD, qty=10), CFG)
    assert world.government.budget == pytest.approx(budget - 10 * world.market.customary_price * CFG.import_premium)


def test_price_cap_duration(world):
    world.tick = 3
    settle(world, d(T.PRICE_CAP, price=4, duration=2), CFG)
    assert world.market.price_cap == 4 and world.market.price_cap_until == 4
