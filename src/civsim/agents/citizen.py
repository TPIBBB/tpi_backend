"""平民的基本行為（rule-based，不使用 LLM）。負責人：Agent。（尚未接進引擎）

行為規格見 citizen_skill.md，修改時兩邊要一起更新。
引擎每天給每位平民一個 CitizenObservation，平民回傳一個 CitizenAction；
動作是否成立（錢夠不夠、市場有沒有糧）由引擎驗證與結算。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CitizenType(str, Enum):
    FARMER_TRADER = "farmer_trader"  # 有產出、有買賣
    SUBSISTENCE = "subsistence"  # 有產出、沒有買賣
    WORKER = "worker"  # 沒有產出、有買賣
    DEPENDENT = "dependent"  # 沒有產出、沒有買賣

    @property
    def produces(self) -> bool:
        return self in (CitizenType.FARMER_TRADER, CitizenType.SUBSISTENCE)

    @property
    def trades(self) -> bool:
        return self in (CitizenType.FARMER_TRADER, CitizenType.WORKER)


class CitizenActionType(str, Enum):
    WORK = "work"  # 有產出的人種糧；工人做工換工資
    BUY_FOOD = "buy_food"
    SELL_FOOD = "sell_food"
    REST = "rest"


# 參數（數值說明見 citizen_skill.md）
BASE_FOOD_PER_DAY = 1.0
GLUTTONY_EXTRA = 0.5  # 最貪吃的人每天多吃 50%
MIN_SAFETY_DAYS = 2
EXTRA_SAFETY_DAYS = 3  # 最不冒險的人多存 3 天
SLOTH_REST_SCALE = 0.5  # 最懶的人糧食夠時有一半的機率休息
SURPLUS_MULTIPLIER = 2  # 糧食超過安全存量的幾倍才考慮賣
MIN_SELL_QTY = 2
GREED_PRICE_SPREAD = 0.2  # 最貪心的人要等價格高於參考價格 10% 才賣
PRICE_EMA_ALPHA = 0.3
MAX_TRADE_QTY = 10


@dataclass
class CitizenPersona:
    """每個值都介於 0～1。"""

    compliance: float = 0.7  # 服從政府政策的機率（政策反應第 2 週實作）
    sloth: float = 0.5
    greed: float = 0.5
    risk_tolerance: float = 0.5
    gluttony: float = 0.5


@dataclass
class CitizenObservation:
    """平民每天看得到的內容。所有平民看到的公開資訊都相同，沒有資訊落差。"""

    tick: int
    citizen_type: CitizenType
    food: float
    money: float
    food_price: float
    policies: dict[str, Any] = field(default_factory=dict)  # 生效中的政府政策（第 2 週使用）


@dataclass
class CitizenAction:
    agent_id: str
    type: CitizenActionType
    qty: int = 0  # 買賣的數量；其他動作為 0
    reason: str = ""  # 只做紀錄，不影響結算


def daily_food_need(persona: CitizenPersona) -> float:
    """每天吃掉的糧食。引擎扣糧時要用同一個公式。"""
    return BASE_FOOD_PER_DAY * (1 + GLUTTONY_EXTRA * persona.gluttony)


def safety_stock(persona: CitizenPersona) -> float:
    """想要保留的糧食量：越不冒險，存越多天。"""
    days = MIN_SAFETY_DAYS + EXTRA_SAFETY_DAYS * (1 - persona.risk_tolerance)
    return days * daily_food_need(persona)


def random_persona(rng: random.Random) -> CitizenPersona:
    return CitizenPersona(
        compliance=rng.random(), sloth=rng.random(), greed=rng.random(),
        risk_tolerance=rng.random(), gluttony=rng.random(),
    )


class CitizenAgent:
    def __init__(self, agent_id: str, persona: CitizenPersona, rng: random.Random):
        self.agent_id = agent_id
        self.persona = persona
        self.rng = rng
        self.ref_price: float | None = None  # 看過的糧價的移動平均

    def reset(self) -> None:
        """社會調回均衡狀態時呼叫，清掉平民自己記住的價格。"""
        self.ref_price = None

    def decide(self, obs: CitizenObservation) -> CitizenAction:
        """每天只回傳一個動作，依 citizen_skill.md 的順序判斷。"""
        p = self.persona
        kind = obs.citizen_type
        ref_price = self._update_ref_price(obs.food_price)
        reserve = safety_stock(p)
        short = obs.food < reserve

        # 1. 糧食不夠：會買賣的人先買糧
        if short and kind.trades:
            qty = min(MAX_TRADE_QTY, math.ceil(reserve - obs.food), self._affordable(obs))
            if qty > 0:
                return self._act(CitizenActionType.BUY_FOOD, "糧食低於安全存量", qty)
            return self._act(CitizenActionType.WORK, "買不起糧，先去工作賺錢" if kind == CitizenType.WORKER
                             else "買不起糧，先去種糧")

        # 2. 糧食夠的時候才會偷懶
        # 每天都抽一次亂數，讓亂數的消耗與當天狀態無關，結果才能由 seed 重現
        lazy = self.rng.random() < p.sloth * SLOTH_REST_SCALE
        if not short and lazy:
            return self._act(CitizenActionType.REST, "糧食夠，今天休息")

        # 3. 依類型行動
        if kind == CitizenType.FARMER_TRADER:
            surplus = int(obs.food - reserve * SURPLUS_MULTIPLIER)
            good_price = obs.food_price >= ref_price * (1 + GREED_PRICE_SPREAD * (p.greed - 0.5))
            if surplus >= MIN_SELL_QTY and good_price:
                return self._act(CitizenActionType.SELL_FOOD, "糧食有剩，價格不錯",
                                 min(surplus, MAX_TRADE_QTY))
            return self._act(CitizenActionType.WORK, "種糧")
        if kind == CitizenType.SUBSISTENCE:
            return self._act(CitizenActionType.WORK, "種糧自己吃")
        if kind == CitizenType.WORKER:
            return self._act(CitizenActionType.WORK, "做工賺錢")
        return self._act(CitizenActionType.REST, "沒有產出也不交易，休息")

    # ---- 工具 ----
    def _act(self, type_: CitizenActionType, reason: str, qty: int = 0) -> CitizenAction:
        return CitizenAction(self.agent_id, type_, qty, reason)

    def _update_ref_price(self, price: float) -> float:
        if self.ref_price is None:
            self.ref_price = price
        else:
            self.ref_price += PRICE_EMA_ALPHA * (price - self.ref_price)
        return self.ref_price

    @staticmethod
    def _affordable(obs: CitizenObservation) -> int:
        if obs.food_price <= 0 or obs.money <= 0:
            return 0
        return int(obs.money / obs.food_price)
