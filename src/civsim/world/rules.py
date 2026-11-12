"""平民行動的驗證與結算。Agent 說什麼都不算數，只有通過這裡的行動才會改變世界。

一天 = 每位平民跑完一輪：依類型，同一天可以生產一次，也可以下一張買單或賣單，兩者不用擇一。

| 類型 | 生產（每天最多一次） | 買賣（每天最多一張單） |
|---|---|---|
| producer_trader（有產出、有買賣） | harvest | buy 或 sell |
| producer_self（有產出、沒買賣） | harvest | — |
| consumer（沒產出、有買賣） | work | buy 或 sell |
| dependent（沒產出、沒買賣） | — | — |

什麼都不做就是 idle。結算順序是先生產、再下單，所以當天收成的糧可以當天賣。
"""

from __future__ import annotations

import math
import random

from civsim.config import CitizenConfig
from civsim.models import Action, ActionType, Citizen, Event, Order, WorldState
from civsim.world.market import place_order


PRODUCTION_ACTIONS = frozenset({ActionType.HARVEST, ActionType.WORK})
TRADE_ACTIONS = frozenset({ActionType.BUY, ActionType.SELL})


def plan_day(citizen_id: str, proposed: list[Action]) -> tuple[Action | None, Action | None, list[Action]]:
    """把平民提出的行動分成（生產, 買賣, 多出來的）。每一類只取第一個，idle 直接忽略。

    這裡只分類，不檢查類型能不能做；能不能做由 validate 判斷，被拒絕的會留下紀錄。
    """
    production = trade = None
    extra: list[Action] = []
    for action in proposed:
        action.agent_id = citizen_id  # 平民不能替別人行動
        if action.type == ActionType.IDLE:
            continue
        if action.type in PRODUCTION_ACTIONS and production is None:
            production = action
        elif action.type in TRADE_ACTIONS and trade is None:
            trade = action
        else:
            extra.append(action)
    return production, trade, extra


def allowed_actions(citizen: Citizen) -> set[ActionType]:
    allowed = {ActionType.IDLE}
    if citizen.type.produces:
        allowed.add(ActionType.HARVEST)
    if citizen.type.trades:
        allowed |= {ActionType.BUY, ActionType.SELL}
        if not citizen.type.produces:
            allowed.add(ActionType.WORK)
    return allowed


def _positive(value, name: str, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} 必須是數字")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} 必須大於 0")
    return float(value)


def validate(world: WorldState, action: Action) -> str | None:
    """回傳 None 表示合法，否則回傳拒絕原因。"""
    c = world.citizens.get(action.agent_id)
    if c is None or not c.alive:
        return "平民不存在或已死亡"
    if action.type not in allowed_actions(c):
        return f"{c.type.value} 不能 {action.type.value}"
    if action.type in (ActionType.BUY, ActionType.SELL):
        try:
            qty = _positive(action.params.get("qty"), "qty")
            price = _positive(action.params.get("price"), "price", allow_zero=action.type == ActionType.SELL)
        except ValueError as e:
            return str(e)
        if action.type == ActionType.BUY and qty * price > c.money + 1e-9:
            return "貨幣不足"
        if action.type == ActionType.SELL and qty > c.food + 1e-9:
            return "存糧不足"
    return None


def settle(world: WorldState, action: Action, config: CitizenConfig, rng: random.Random) -> Event:
    """執行一個已驗證的行動並回傳事件紀錄。買賣只是下單，成交在當天收盤時結算。"""
    c = world.citizens[action.agent_id]
    payload: dict = {"params": action.params}

    if action.type == ActionType.HARVEST:
        amount = rng.uniform(config.harvest_min, config.harvest_max) * world.food_multiplier
        c.food += amount
        payload["output"] = round(amount, 4)
    elif action.type == ActionType.WORK:
        c.money += config.wage
        payload["income"] = config.wage
    elif action.type in (ActionType.BUY, ActionType.SELL):
        place_order(world, Order(c.id, action.type.value,
                                 float(action.params["qty"]), float(action.params["price"])))

    return Event(world.tick, f"action:{action.type.value}", c.id, True, payload, action.reason)


def end_of_tick_upkeep(world: WorldState, config: CitizenConfig) -> list[Event]:
    """每天結束時每人吃掉 food_per_day 的糧食；不夠吃就算挨餓一天（目前不會餓死）。"""
    events: list[Event] = []
    for c in world.living():
        if c.food >= config.food_per_day - 1e-9:
            c.food = max(0.0, c.food - config.food_per_day)
            c.hungry_days = 0
        else:
            c.food = 0.0
            c.hungry_days += 1
            events.append(Event(world.tick, "world:hungry", c.id, True, {"hungry_days": c.hungry_days}))
    return events
