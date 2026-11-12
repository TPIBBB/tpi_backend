import random
from dataclasses import replace

from civsim.agents.rule_based import RuleBasedCitizen
from civsim.config import SimConfig
from civsim.models import Action, ActionType, CitizenType
from civsim.world import rules
from civsim.world.setup import create_world


def make(type_: CitizenType, **state):
    config = SimConfig()
    world = create_world(config, random.Random(0))
    c = next(c for c in world.citizens.values() if c.type == type_)
    for k, v in state.items():
        setattr(c, k, v)
    c.persona = replace(c.persona, sloth=0.0)
    return world, c, RuleBasedCitizen(c.id, random.Random(0), config)


def decide(world, c, agent, price_cap=None):
    from civsim.models import Observation

    m = world.market
    return agent.decide(Observation(world.tick, c, m.price, m.customary_price, price_cap, []))


def test_initial_world_matches_population():
    config = SimConfig()
    world = create_world(config, random.Random(0))
    assert len(world.citizens) == config.n_citizens
    defiant = sum(1 for c in world.citizens.values() if not c.persona.complies)
    assert defiant == round(config.n_citizens * config.citizens.noncompliance_rate)


def types(actions):
    return [a.type for a in actions]


def test_consumer_works_and_buys_on_the_same_day_when_low():
    world, c, agent = make(CitizenType.CONSUMER, food=0.5, money=100)
    work, buy = decide(world, c, agent)
    assert work.type == ActionType.WORK and buy.type == ActionType.BUY
    assert rules.validate(world, buy) is None
    assert buy.params["price"] > world.market.customary_price  # 快沒糧了願意多付
    world, c, agent = make(CitizenType.CONSUMER, food=50, money=100)
    assert types(decide(world, c, agent)) == [ActionType.WORK]


def test_farmer_harvests_and_sells_on_the_same_day():
    world, c, agent = make(CitizenType.PRODUCER_TRADER, food=8)
    c.persona = replace(c.persona, risk_tolerance=0.5, gluttony=0.0)  # 安全存量 4 天：多 4 單位可賣，又不到 12 天
    harvest, sell = decide(world, c, agent)
    assert harvest.type == ActionType.HARVEST and sell.type == ActionType.SELL
    assert rules.validate(world, sell) is None
    world, c, agent = make(CitizenType.PRODUCER_TRADER, food=40)  # 存糧很多：不收成，只賣
    assert types(decide(world, c, agent)) == [ActionType.SELL]
    world, c, agent = make(CitizenType.PRODUCER_TRADER, food=0, money=30)  # 存糧不夠：收成，也買糧
    harvest, buy = decide(world, c, agent)
    assert harvest.type == ActionType.HARVEST and buy.type == ActionType.BUY
    assert rules.validate(world, buy) is None


def test_defiant_farmer_hoards_under_price_cap():
    world, c, agent = make(CitizenType.PRODUCER_TRADER, food=40)
    c.persona = replace(c.persona, complies=False)
    assert ActionType.SELL not in types(decide(world, c, agent, price_cap=3.0))  # 不服從：囤糧觀望
    assert types(decide(world, c, agent)) == [ActionType.SELL]  # 沒有價格上限就照常賣
    c.persona = replace(c.persona, complies=True)
    assert types(decide(world, c, agent, price_cap=3.0)) == [ActionType.SELL]  # 服從的人照常賣


def test_consumer_never_sells():
    world, c, agent = make(CitizenType.CONSUMER, food=100, money=100)
    assert ActionType.SELL not in types(decide(world, c, agent))


def test_lazy_citizen_skips_production_but_still_trades():
    world, c, agent = make(CitizenType.CONSUMER, food=0.5, money=100)
    c.persona = replace(c.persona, sloth=1.0)
    assert types(decide(world, c, agent)) == [ActionType.BUY]
    world, c, agent = make(CitizenType.PRODUCER_SELF, food=50)
    assert types(decide(world, c, agent)) == [ActionType.IDLE]  # 存糧夠多，什麼都不做


def test_plan_day_keeps_one_production_and_one_trade():
    a = lambda t: Action("someone_else", t, {})  # noqa: E731
    made, trade, extra = rules.plan_day("c01", [a(ActionType.IDLE), a(ActionType.SELL), a(ActionType.HARVEST),
                                                a(ActionType.BUY), a(ActionType.WORK)])
    assert made.type == ActionType.HARVEST and trade.type == ActionType.SELL
    assert types(extra) == [ActionType.BUY, ActionType.WORK]
    assert made.agent_id == trade.agent_id == "c01"  # 平民不能替別人行動


def test_types_limit_actions():
    world, dep, _ = make(CitizenType.DEPENDENT)
    assert rules.validate(world, Action(dep.id, ActionType.BUY, {"qty": 1, "price": 1})) is not None
    world, selfc, _ = make(CitizenType.PRODUCER_SELF)
    assert rules.validate(world, Action(selfc.id, ActionType.SELL, {"qty": 1, "price": 1})) is not None
    world, con, _ = make(CitizenType.CONSUMER, money=1)
    assert rules.validate(world, Action(con.id, ActionType.BUY, {"qty": 1, "price": 5})) == "貨幣不足"


def test_hungry_but_never_dies():
    world, c, _ = make(CitizenType.DEPENDENT, food=0)
    for _ in range(10):
        rules.end_of_tick_upkeep(world, SimConfig().citizens)
    assert c.alive and c.hungry_days == 10
