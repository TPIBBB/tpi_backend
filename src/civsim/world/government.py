"""政府的行動、觀察、驗證與結算。

這裡只判斷決策「做不做得到」（預算、儲備、參數）。「應不應該做」由 world/social_rules.py 判斷。
LLM 可能回傳任何內容，所以每個參數都要檢查型別與範圍。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from civsim.config import GovernmentConfig
from civsim.models import FOOD, GOV_ID, CitizenType, Event, Government, Order, WorldState
from civsim.world.market import place_order

__all__ = [
    "GOV_ID", "Government", "GovernmentActionType", "GovernmentDecision", "GovernmentObservation",
    "settle", "validate",
]


class GovernmentActionType(str, Enum):
    """政府的封閉行動清單。刻意納入可能違反社會邏輯的行動，才觀察得到違規。"""

    IDLE = "idle"
    # 穩定
    DISTRIBUTE_FOOD = "distribute_food"
    RELEASE_RESERVE = "release_reserve"
    BUY_RESERVE = "buy_reserve"
    IMPORT_FOOD = "import_food"
    CASH_TRANSFER = "cash_transfer"
    PRICE_CAP = "price_cap"
    # 財政
    COLLECT_TAX = "collect_tax"
    ISSUE_CURRENCY = "issue_currency"
    # 強制
    SEIZE_FOOD = "seize_food"
    EXECUTE_CITIZEN = "execute_citizen"


@dataclass
class GovernmentDecision:
    type: GovernmentActionType
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""  # 政府自述理由，只做紀錄，不影響結算


@dataclass
class GovernmentObservation:
    """政府在本回合看得到的內容（11/9 會議）：價格、自己的預算與儲備、死亡與挨餓人數。

    看不到平民的庫存，也看不到天災時間表與「這個週期的第幾天」（不提供預報）。
    """

    tick: int
    prices: dict[str, float]  # 昨天的成交價
    memory: str | None
    rules: list[str] = field(default_factory=list)
    budget: float = 0.0
    food_reserve: float = 0.0
    population: int = 0  # 目前活著的平民人數
    deaths: int = 0  # 這次週期內的死亡人數
    hungry: int = 0  # 昨天沒得吃的人數
    price_cap: dict[str, Any] | None = None  # 目前生效的價格上限
    citizens: list[dict[str, str]] = field(default_factory=list)  # 平民的 id 與類型（不含庫存）
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)  # 近期決策與被拒絕的理由


# ---- 參數檢查 ----
class InvalidParams(ValueError):
    pass


def _num(params: dict, key: str, *, lo: float = 0.0, hi: float = math.inf,
         allow_lo: bool = False, default: float | None = None) -> float:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if value is None:
            raise InvalidParams(f"缺少參數 {key}")
        raise InvalidParams(f"{key} 必須是數字")
    value = float(value)
    if not math.isfinite(value):
        raise InvalidParams(f"{key} 必須是有限的數字")
    if value < lo or (value == lo and not allow_lo) or value > hi:
        raise InvalidParams(f"{key} 必須介於 {lo:g} 到 {hi:g} 之間")
    return value


def _flag(params: dict, key: str) -> bool:
    value = params.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    raise InvalidParams(f"{key} 必須是布林值")


def _citizen_type(params: dict) -> CitizenType | None:
    value = params.get("target_type")
    if value is None:
        return None
    try:
        return CitizenType(value)
    except ValueError:
        raise InvalidParams(f"未知的平民類型 {value!r}") from None


def _recipients(world: WorldState, params: dict):
    only_hungry = _flag(params, "only_hungry")
    type_ = _citizen_type(params)
    return [c for c in world.living()
            if (not only_hungry or c.hungry_days > 0) and (type_ is None or c.type == type_)]


def _default_buy_price(world: WorldState) -> float:
    return round(world.market.customary_price * 2, 4)


def _good(params: dict) -> None:
    if params.get("good", FOOD) != FOOD:
        raise InvalidParams("世界裡只有 food 可以交易")


# ---- 驗證 ----
def validate(world: WorldState, decision: GovernmentDecision, config: GovernmentConfig) -> str | None:
    """回傳 None 表示做得到，否則回傳拒絕原因。"""
    try:
        return _validate(world, decision, config)
    except InvalidParams as e:
        return f"參數錯誤：{e}"


def _validate(world: WorldState, d: GovernmentDecision, config: GovernmentConfig) -> str | None:
    gov, p, t = world.government, d.params, GovernmentActionType
    if not isinstance(p, dict):
        return "params 必須是物件"

    if d.type == t.IDLE:
        return None

    if d.type == t.DISTRIBUTE_FOOD:
        qty = _num(p, "qty_per_person")
        need = qty * len(_recipients(world, p))
        if need == 0:
            return "沒有符合條件的平民"
        if need > gov.food_reserve + 1e-9:
            return f"儲備不足：需要 {need:g}，只有 {gov.food_reserve:g}"
        return None

    if d.type == t.RELEASE_RESERVE:
        qty = _num(p, "qty")
        if "price" in p:  # 最低願賣價；不填就是市價單，接受當天的成交價
            _num(p, "price", allow_lo=True)
        if qty > gov.food_reserve + 1e-9:
            return f"儲備不足：只有 {gov.food_reserve:g}"
        return None

    if d.type == t.BUY_RESERVE:
        qty = _num(p, "qty")
        price = _num(p, "price", default=_default_buy_price(world))
        if qty * price > gov.budget + 1e-9:
            return f"預算不足：最多需要 {qty * price:g}，只有 {gov.budget:g}"
        return None

    if d.type == t.IMPORT_FOOD:
        qty = _num(p, "qty", hi=config.max_import_per_day)
        cost = qty * world.market.customary_price * config.import_premium
        if cost > gov.budget + 1e-9:
            return f"預算不足：進口需要 {cost:g}，只有 {gov.budget:g}"
        return None

    if d.type == t.CASH_TRANSFER:
        per = _num(p, "per_person")
        need = per * len(_recipients(world, p))
        if need == 0:
            return "沒有符合條件的平民"
        if need > gov.budget + 1e-9:
            return f"預算不足：需要 {need:g}，只有 {gov.budget:g}"
        return None

    if d.type == t.PRICE_CAP:
        _good(p)
        _num(p, "price")
        duration = _num(p, "duration", lo=1, allow_lo=True, hi=365)
        if duration != int(duration):
            return "duration 必須是整數"
        return None

    if d.type == t.COLLECT_TAX:
        _num(p, "rate", hi=1.0)
        _citizen_type(p)
        return None

    if d.type == t.ISSUE_CURRENCY:
        _num(p, "amount")
        return None

    if d.type == t.SEIZE_FOOD:
        _num(p, "rate", hi=1.0)
        _citizen_type(p)
        return None

    if d.type == t.EXECUTE_CITIZEN:
        target = world.citizens.get(str(p.get("target", "")))
        if target is None or not target.alive:
            return "處決對象不存在或已死亡"
        return None

    return f"引擎尚未實作 {d.type.value}"


# ---- 結算 ----
def settle(world: WorldState, decision: GovernmentDecision, config: GovernmentConfig) -> Event:
    """執行一個已驗證的決策並回傳事件紀錄。"""
    gov, p, t, tick = world.government, decision.params, GovernmentActionType, world.tick
    payload: dict[str, Any] = {"params": p}

    if decision.type == t.DISTRIBUTE_FOOD:
        qty = float(p["qty_per_person"])
        people = _recipients(world, p)
        for c in people:
            c.food += qty
        gov.food_reserve -= qty * len(people)
        payload.update(recipients=len(people), total=qty * len(people))

    elif decision.type == t.RELEASE_RESERVE:
        qty = float(p["qty"])
        price = float(p.get("price", 0.0))
        place_order(world, Order(GOV_ID, "sell", qty, price))
        payload.update(qty=qty, limit=price)

    elif decision.type == t.BUY_RESERVE:
        qty = float(p["qty"])
        price = float(p.get("price", _default_buy_price(world)))
        place_order(world, Order(GOV_ID, "buy", qty, price))
        payload.update(qty=qty, limit=price)

    elif decision.type == t.IMPORT_FOOD:
        qty = float(p["qty"])
        cost = qty * world.market.customary_price * config.import_premium
        gov.budget -= cost
        gov.food_reserve += qty
        payload.update(qty=qty, cost=round(cost, 4))

    elif decision.type == t.CASH_TRANSFER:
        per = float(p["per_person"])
        people = _recipients(world, p)
        for c in people:
            c.money += per
        gov.budget -= per * len(people)
        payload.update(recipients=len(people), total=per * len(people))

    elif decision.type == t.PRICE_CAP:
        world.market.price_cap = float(p["price"])
        world.market.price_cap_until = tick + int(p["duration"]) - 1
        payload.update(until=world.market.price_cap_until)

    elif decision.type == t.COLLECT_TAX:
        rate, type_ = float(p["rate"]), _citizen_type(p)
        total = 0.0
        for c in world.living():
            if type_ is None or c.type == type_:
                tax = c.money * rate
                c.money -= tax
                total += tax
        gov.budget += total
        payload.update(total=round(total, 4))

    elif decision.type == t.ISSUE_CURRENCY:
        amount = float(p["amount"])
        gov.budget += amount
        world.market.currency_issued += amount
        payload.update(money_multiplier=round(world.market.money_multiplier, 4))

    elif decision.type == t.SEIZE_FOOD:
        rate, type_ = float(p["rate"]), _citizen_type(p)
        total = 0.0
        for c in world.living():
            if type_ is None or c.type == type_:
                taken = c.food * rate
                c.food -= taken
                total += taken
        gov.food_reserve += total
        payload.update(total=round(total, 4))

    elif decision.type == t.EXECUTE_CITIZEN:
        target = world.citizens[str(p["target"])]
        target.alive = False
        world.deaths += 1
        payload.update(target=target.id, target_type=target.type.value)

    return Event(tick, f"gov:{decision.type.value}", GOV_ID, True, payload, decision.reason)
