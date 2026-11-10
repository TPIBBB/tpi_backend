"""世界中的核心資料結構。

原則：Agent 的「大腦」（agents/）只能讀到 Observation、只能提出 Action 或 GovernmentDecision；
真正的狀態（Citizen / Government / WorldState）只由模擬引擎修改。

世界只有一種商品「糧食」和「貨幣」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

FOOD = "food"
GOV_ID = "gov"  # 政府在事件紀錄與委託簿裡的 id


class CitizenType(str, Enum):
    """平民的四種特性：有無產出 × 有無買賣。"""

    PRODUCER_TRADER = "producer_trader"  # 有產出、有買賣：種糧，把多的賣掉
    PRODUCER_SELF = "producer_self"  # 有產出、沒買賣：自耕自食，多的自己囤著
    CONSUMER = "consumer"  # 沒產出、有買賣：打工領固定收入，用錢買糧
    DEPENDENT = "dependent"  # 沒產出、沒買賣：只吃存糧，吃完只能靠政府

    @property
    def produces(self) -> bool:
        return self in (CitizenType.PRODUCER_TRADER, CitizenType.PRODUCER_SELF)

    @property
    def trades(self) -> bool:
        return self in (CitizenType.PRODUCER_TRADER, CitizenType.CONSUMER)


class ActionType(str, Enum):
    """平民一天只能做一個動作。吃東西是每天結束時自動發生的，不算動作。"""

    HARVEST = "harvest"  # 有產出的平民：收成
    WORK = "work"  # 沒產出、有買賣的平民：打工領固定收入
    BUY = "buy"  # params: qty, price（願意付的最高單價）
    SELL = "sell"  # params: qty, price（願意接受的最低單價）
    IDLE = "idle"


@dataclass
class Persona:
    """平民的人格。數值介於 0~1，complies 是會不會遵守政府政策。

    TODO(Agent 組)：persona 如何影響行為由 Agent 組定義，引擎只負責保存。
    """

    complies: bool = True
    sloth: float = 0.0  # 懶惰：該工作時偷懶的機率
    greed: float = 0.5  # 貪婪：賣得比較貴
    risk_tolerance: float = 0.5  # 冒險：存糧的安全天數比較少
    gluttony: float = 0.0  # 暴食：想多存一點糧


@dataclass
class Citizen:
    id: str
    type: CitizenType
    persona: Persona
    food: float
    money: float
    alive: bool = True
    hungry_days: int = 0  # 連續沒得吃的天數（目前不會餓死，只做紀錄）


@dataclass
class Action:
    agent_id: str
    type: ActionType
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""  # Agent 自述理由，只做紀錄，不影響結算


@dataclass
class Event:
    """每一次行動或世界事件的結算紀錄，會寫入 Recorder。"""

    tick: int
    kind: str
    actor: str | None
    success: bool
    payload: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass
class Observation:
    """平民本回合看得到的內容。所有平民看到的公共資訊都一樣，沒有資訊落差。"""

    tick: int
    self_state: Citizen
    price: float  # 昨天的成交價
    customary_price: float  # 習慣價格：大家心中糧食「應該」值多少（已含貨幣量倍率）
    price_cap: float | None  # 政府設定的價格上限
    government_actions: list[dict[str, Any]]  # 昨天政府成功執行的決策（平民對政府的反應用）


@dataclass
class Order:
    """集合競價的一張單。資源在下單時就先扣住，沒成交的部分收盤後退回。"""

    owner: str
    side: str  # buy | sell
    qty: float
    price: float  # 買單：最高願付價；賣單：最低願賣價


@dataclass
class Market:
    price: float  # 最近一次的成交價；某天沒有成交就沿用前一天
    base_price: float  # 糧食的基準價值（貨幣量倍率之前）
    initial_money: float  # 初始的貨幣總量（平民 + 政府）
    currency_issued: float = 0.0  # 政府累計發行的貨幣
    price_cap: float | None = None
    price_cap_until: int | None = None  # 價格上限有效到這一回合（含）
    orders: list[Order] = field(default_factory=list)

    @property
    def money_multiplier(self) -> float:
        """貨幣量倍率：目前貨幣量 / 初始貨幣量。發行貨幣會讓習慣價格跟著上升。"""
        return (self.initial_money + self.currency_issued) / self.initial_money

    @property
    def customary_price(self) -> float:
        return self.base_price * self.money_multiplier


@dataclass
class Government:
    budget: float
    food_reserve: float


@dataclass
class WorldState:
    tick: int
    citizens: dict[str, Citizen]
    government: Government
    market: Market
    food_multiplier: float = 1.0  # 今天的收成倍率（天災時小於 1）
    phase: str = "stable"  # stable | disaster | evaluation
    disaster_id: int | None = None  # 目前所在的天災週期，從 1 開始
    deaths: int = 0  # 這次天災週期內的死亡人數（調回均衡狀態時歸零）

    def living(self) -> list[Citizen]:
        return [c for c in self.citizens.values() if c.alive]
