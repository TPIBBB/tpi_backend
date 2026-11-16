"""糧食市場：每天一次集合競價（call auction）。

所有買單、賣單（平民和政府）在當天收齊後一次撮合，找出讓成交量最大的單一價格，
所有成交都用這個價格。這個價格就是當天的市價，均衡價格也由它定義（見 world/equilibrium.py）。

下單時資源就先扣住（買單扣錢、賣單扣糧），沒成交的部分收盤後退回，
同一天的政府決策才不會重複動用同一筆預算或儲備。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from civsim.models import GOV_ID, Event, Order, WorldState

EPS = 1e-9


@dataclass
class ClearingResult:
    price: float  # 成交價；沒有成交時沿用前一天的價格
    volume: float
    traded: bool
    capped: bool  # 價格被政府的上限壓住
    demand: float  # 當天所有買單的總量
    supply: float  # 當天所有賣單的總量
    filled: dict[int, float] = field(default_factory=dict)  # 委託簿中第幾張單 → 成交量


def _volume_at(p: float, bids: list[Order], asks: list[Order]) -> tuple[float, float]:
    demand = sum(o.qty for o in bids if o.price >= p - EPS)
    supply = sum(o.qty for o in asks if o.price <= p + EPS)
    return demand, supply


def clear(orders: list[Order], last_price: float, price_cap: float | None,
          rng: random.Random) -> ClearingResult:
    bids = [o for o in orders if o.side == "buy" and o.qty > 0]
    asks = [o for o in orders if o.side == "sell" and o.qty > 0]
    total_demand = sum(o.qty for o in bids)
    total_supply = sum(o.qty for o in asks)

    # 候選價格：每張單的限價，以及相鄰限價的中點（價格才不會永遠貼在某一方的報價上）
    prices = sorted({o.price for o in bids + asks})
    candidates = prices + [(a + b) / 2 for a, b in zip(prices, prices[1:])]

    def best(cands: list[float]) -> tuple[float, float] | None:
        """回傳 (價格, 成交量)。成交量最大 → 買賣量差最小 → 最接近昨天的價格。"""
        scored = []
        for p in cands:
            d, s = _volume_at(p, bids, asks)
            scored.append((-min(d, s), abs(d - s), abs(p - last_price), p))
        if not scored:
            return None
        neg_vol, _, _, p = min(scored)
        return p, -neg_vol

    chosen = best(candidates)
    capped = False
    if price_cap is not None and chosen is not None and chosen[1] > EPS and chosen[0] > price_cap + EPS:
        capped = True
        chosen = best([p for p in candidates if p <= price_cap] + [price_cap])

    if chosen is None or chosen[1] <= EPS:
        # 沒有成交：有人出更高的價還買不到，價格就往最高買價走；有人更低的價還賣不掉，就往最低賣價走
        price = last_price
        best_bid = max((o.price for o in bids), default=None)
        best_ask = min((o.price for o in asks), default=None)
        if best_bid is not None and best_bid > price:
            price = best_bid
        elif best_ask is not None and best_ask < price:
            price = best_ask
        if price_cap is not None and price > price_cap:
            price, capped = price_cap, True
        return ClearingResult(price, 0.0, False, capped, total_demand, total_supply)

    price, volume = chosen
    filled = _allocate(orders, price, volume, rng)
    return ClearingResult(price, volume, True, capped, total_demand, total_supply, filled)


def _allocate(orders: list[Order], price: float, volume: float, rng: random.Random) -> dict[int, float]:
    """價格較好的單先成交；同價位的單隨機排序（排隊順序不該固定對誰有利）。"""
    filled: dict[int, float] = {}
    for side, eligible, better in (
        ("buy", lambda o: o.price >= price - EPS, lambda i: -orders[i].price),
        ("sell", lambda o: o.price <= price + EPS, lambda i: orders[i].price),
    ):
        book = [i for i, o in enumerate(orders) if o.side == side and o.qty > 0 and eligible(o)]
        rng.shuffle(book)
        book.sort(key=better)
        left = volume
        for i in book:
            if left <= EPS:
                break
            qty = min(orders[i].qty, left)
            filled[i] = qty
            left -= qty
    return filled


def place_order(world: WorldState, order: Order) -> None:
    """把單放進今天的委託簿，並先扣住資源。呼叫前必須先驗證資源足夠。"""
    if order.owner == GOV_ID:
        if order.side == "buy":
            world.government.budget -= order.qty * order.price
        else:
            world.government.food_reserve -= order.qty
    else:
        citizen = world.citizens[order.owner]
        if order.side == "buy":
            citizen.money -= order.qty * order.price
        else:
            citizen.food -= order.qty
    world.market.orders.append(order)


def settle_market(world: WorldState, rng: random.Random) -> tuple[ClearingResult, list[Event]]:
    """撮合今天的委託簿、交割成交的部分、退回沒成交的部分。"""
    market = world.market
    cap = market.price_cap if market.price_cap_until is not None and world.tick <= market.price_cap_until else None
    result = clear(market.orders, market.price, cap, rng)

    events: list[Event] = []
    for i, o in enumerate(market.orders):
        qty = result.filled.get(i, 0.0)
        _credit(world, o, qty, result.price)
        if qty > EPS:
            events.append(Event(world.tick, f"trade:{o.side}", o.owner, True,
                                {"qty": round(qty, 4), "price": result.price, "limit": o.price}))

    market.orders = []
    market.price = result.price
    return result, events


def _credit(world: WorldState, o: Order, qty: float, price: float) -> None:
    """交割成交量 qty，並退回沒成交的部分與多扣的錢。"""
    unfilled = o.qty - qty
    if o.owner == GOV_ID:
        gov = world.government
        if o.side == "buy":
            gov.food_reserve += qty
            gov.budget += qty * (o.price - price) + unfilled * o.price
        else:
            gov.budget += qty * price
            gov.food_reserve += unfilled
        return
    c = world.citizens[o.owner]
    if o.side == "buy":
        c.food += qty
        c.money += qty * (o.price - price) + unfilled * o.price
    else:
        c.money += qty * price
        c.food += unfilled
