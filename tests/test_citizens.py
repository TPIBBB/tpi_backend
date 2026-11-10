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


def decide(world, c, agent):
    from civsim.models import Observation

    m = world.market
    return agent.decide(Observation(world.tick, c, m.price, m.customary_price, None, []))


def test_initial_world_matches_population():
    config = SimConfig()
    world = create_world(config, random.Random(0))
    assert len(world.citizens) == config.n_citizens
    defiant = sum(1 for c in world.citizens.values() if not c.persona.complies)
    assert defiant == round(config.n_citizens * config.citizens.noncompliance_rate)


def test_consumer_buys_when_low_and_works_otherwise():
    world, c, agent = make(CitizenType.CONSUMER, food=0.5, money=100)
    [a] = decide(world, c, agent)
    assert a.type == ActionType.BUY and rules.validate(world, a) is None
    assert a.params["price"] > world.market.customary_price  # 快沒糧了願意多付
    world, c, agent = make(CitizenType.CONSUMER, food=50, money=100)
    assert decide(world, c, agent)[0].type == ActionType.WORK


def test_farmer_sells_surplus_and_harvests_otherwise():
    world, c, agent = make(CitizenType.PRODUCER_TRADER, food=40)
    [a] = decide(world, c, agent)
    assert a.type == ActionType.SELL and rules.validate(world, a) is None
    world, c, agent = make(CitizenType.PRODUCER_TRADER, food=0)
    assert decide(world, c, agent)[0].type == ActionType.HARVEST


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
