import random

import pytest

from civsim.config import SimConfig
from civsim.models import GOV_ID, Order
from civsim.world.market import clear, place_order, settle_market
from civsim.world.setup import create_world


def rng():
    return random.Random(0)


def test_clears_where_supply_meets_demand():
    orders = [Order("b1", "buy", 5, 10), Order("b2", "buy", 5, 6), Order("b3", "buy", 5, 3),
              Order("s1", "sell", 5, 4), Order("s2", "sell", 5, 5), Order("s3", "sell", 5, 9)]
    r = clear(orders, last_price=5, price_cap=None, rng=rng())
    assert r.volume == 10
    assert 5 <= r.price <= 6  # 第 10 單位的買價 6、賣價 5 之間
    assert sum(r.filled.values()) == 20  # 買賣各 10


def test_no_cross_moves_price_toward_unmet_bid():
    r = clear([Order("b", "buy", 3, 8)], last_price=5, price_cap=None, rng=rng())
    assert not r.traded and r.price == 8


def test_no_cross_moves_price_toward_unsold_ask():
    r = clear([Order("s", "sell", 3, 2)], last_price=5, price_cap=None, rng=rng())
    assert not r.traded and r.price == 2


def test_price_cap_limits_price_and_is_flagged():
    orders = [Order("b", "buy", 5, 10), Order("s", "sell", 5, 8)]
    r = clear(orders, last_price=5, price_cap=6, rng=rng())
    assert r.capped and r.price <= 6 and r.volume == 0  # 上限低於賣價，沒有人願意賣


def test_partial_fill_refunds_escrow():
    world = create_world(SimConfig(), random.Random(0))
    buyer, seller = list(world.citizens.values())[:2]
    buyer.money, seller.food, seller.money = 100.0, 10.0, 0.0
    place_order(world, Order(buyer.id, "buy", 10, 6))
    place_order(world, Order(seller.id, "sell", 4, 4))
    assert buyer.money == pytest.approx(40) and seller.food == pytest.approx(6)
    result, _ = settle_market(world, rng())
    assert result.volume == pytest.approx(4)
    p = result.price
    assert buyer.money == pytest.approx(100 - 4 * p)
    assert seller.money == pytest.approx(4 * p)
    assert seller.food == pytest.approx(6) and world.market.orders == []


def test_government_orders_use_reserve_and_budget():
    world = create_world(SimConfig(), random.Random(0))
    gov = world.government
    budget, reserve = gov.budget, gov.food_reserve
    place_order(world, Order(GOV_ID, "sell", 10, 0))
    settle_market(world, rng())  # 沒有買家：儲備退回
    assert gov.food_reserve == pytest.approx(reserve) and gov.budget == pytest.approx(budget)


def test_money_and_food_are_conserved_in_trade():
    world = create_world(SimConfig(), random.Random(0))
    cs = list(world.citizens.values())
    total = lambda: (sum(c.money for c in cs) + world.government.budget, sum(c.food for c in cs))
    for c in cs[:10]:
        c.money, c.food = 50.0, 10.0
    before = total()
    for i, c in enumerate(cs[:10]):
        side = "buy" if i % 2 else "sell"
        place_order(world, Order(c.id, side, 3, 4 + i * 0.3))
    settle_market(world, rng())
    after = total()
    assert after == pytest.approx(before)
