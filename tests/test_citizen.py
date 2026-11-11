import random

import pytest

from civsim.agents.citizen import (
    MAX_TRADE_QTY,
    CitizenAction,
    CitizenActionType,
    CitizenAgent,
    CitizenObservation,
    CitizenPersona,
    CitizenType,
    daily_food_need,
    random_persona,
    safety_stock,
)

T = CitizenType
A = CitizenActionType
DILIGENT = CitizenPersona(sloth=0.0)  # 不會偷懶，結果不受亂數影響


def obs(kind: CitizenType, food: float, money: float = 50.0, price: float = 5.0, tick: int = 0):
    return CitizenObservation(tick=tick, citizen_type=kind, food=food, money=money, food_price=price)


def agent(persona: CitizenPersona = DILIGENT, seed: int = 0) -> CitizenAgent:
    return CitizenAgent("c01", persona, random.Random(seed))


# ---- 計算方式 ----
def test_food_need_and_safety_stock_follow_persona():
    assert daily_food_need(CitizenPersona(gluttony=0)) == 1.0
    assert daily_food_need(CitizenPersona(gluttony=1)) == 1.5
    cautious = CitizenPersona(risk_tolerance=0, gluttony=0)
    bold = CitizenPersona(risk_tolerance=1, gluttony=0)
    assert safety_stock(cautious) == 5 and safety_stock(bold) == 2


def test_type_flags():
    assert [(k.produces, k.trades) for k in CitizenType] == [
        (True, True), (True, False), (False, True), (False, False)]


# ---- 每天只做一個動作 ----
@pytest.mark.parametrize("kind", list(CitizenType))
def test_returns_exactly_one_action(kind):
    action = agent().decide(obs(kind, food=3))
    assert isinstance(action, CitizenAction) and action.agent_id == "c01"


# ---- 糧食不夠 ----
@pytest.mark.parametrize("kind", [T.FARMER_TRADER, T.WORKER])
def test_traders_buy_up_to_safety_stock(kind):
    reserve = safety_stock(DILIGENT)  # 3.5 × 1.25 = 4.375
    action = agent().decide(obs(kind, food=1))
    assert action.type == A.BUY_FOOD and action.qty == 4
    assert 1 + action.qty >= reserve


def test_buy_is_limited_by_money_and_trade_cap():
    assert agent().decide(obs(T.WORKER, food=0, money=12, price=5)).qty == 2
    hungry_cautious = CitizenPersona(sloth=0, risk_tolerance=0, gluttony=1)  # 安全存量 7.5
    big = agent(hungry_cautious).decide(obs(T.WORKER, food=-10, money=1000))
    assert big.qty == MAX_TRADE_QTY


@pytest.mark.parametrize("kind, expected", [(T.WORKER, "工作賺錢"), (T.FARMER_TRADER, "種糧")])
def test_cannot_afford_food_goes_to_work(kind, expected):
    action = agent().decide(obs(kind, food=0, money=1, price=5))
    assert action.type == A.WORK and expected in action.reason


def test_non_traders_never_trade_even_when_short():
    assert agent().decide(obs(T.SUBSISTENCE, food=0)).type == A.WORK
    assert agent().decide(obs(T.DEPENDENT, food=0)).type == A.REST


# ---- 糧食夠 ----
def test_lazy_citizen_rests_only_when_food_is_enough():
    lazy = CitizenPersona(sloth=1.0)
    rests = [agent(lazy, seed=s).decide(obs(T.WORKER, food=20)).type == A.REST for s in range(200)]
    assert 0.35 < sum(rests) / len(rests) < 0.65  # 最懶的人約一半的機率休息
    assert all(agent(lazy, seed=s).decide(obs(T.WORKER, food=0)).type == A.BUY_FOOD for s in range(50))


def test_farmer_trader_sells_surplus_when_price_is_good():
    action = agent().decide(obs(T.FARMER_TRADER, food=20, price=5))
    assert action.type == A.SELL_FOOD and action.qty == MAX_TRADE_QTY  # 多出約 11 單位，上限 10


def test_farmer_trader_keeps_small_surplus_and_works():
    assert agent().decide(obs(T.FARMER_TRADER, food=9.5)).type == A.WORK  # 只多 0.75 單位


def test_greedy_farmer_waits_for_higher_price():
    greedy = agent(CitizenPersona(sloth=0, greed=1.0))
    greedy.decide(obs(T.FARMER_TRADER, food=20, price=5))  # 參考價格 = 5
    assert greedy.decide(obs(T.FARMER_TRADER, food=20, price=5.2)).type == A.WORK  # 要 ≥ 5.5 才賣
    generous = agent(CitizenPersona(sloth=0, greed=0.0))
    generous.decide(obs(T.FARMER_TRADER, food=20, price=5))
    assert generous.decide(obs(T.FARMER_TRADER, food=20, price=4.6)).type == A.SELL_FOOD


@pytest.mark.parametrize("kind, expected", [
    (T.SUBSISTENCE, A.WORK), (T.WORKER, A.WORK), (T.DEPENDENT, A.REST)])
def test_default_action_by_type(kind, expected):
    assert agent().decide(obs(kind, food=20)).type == expected


# ---- 記憶與重現 ----
def test_reference_price_is_moving_average_and_reset_clears_it():
    a = agent()
    a.decide(obs(T.WORKER, food=20, price=5))
    a.decide(obs(T.WORKER, food=20, price=10))
    assert a.ref_price == pytest.approx(6.5)
    a.reset()
    assert a.ref_price is None


def test_same_seed_gives_same_decisions():
    def run(seed):
        rng = random.Random(seed)
        a = CitizenAgent("c01", random_persona(rng), rng)
        return [a.decide(obs(T.FARMER_TRADER, food=f, price=5 + f % 3, tick=t)).type
                for t, f in enumerate(range(0, 30, 2))]

    assert run(1) == run(1)
