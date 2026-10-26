"""世界中的核心資料結構。

原則：Agent 的「大腦」（agents/）只能讀到 Observation、只能提出 Action；
真正的狀態（AgentState / WorldState）只由模擬引擎修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

GOODS = ("food", "wood", "tools")


class ActionType(str, Enum):
    WORK = "work"
    TRADE = "trade"  # params: side=buy|sell, good, qty
    SHARE_INFO = "share_info"  # params: target, info_key
    REQUEST_PERMISSION = "request_permission"  # params: permission, target(可授權者)
    GRANT_PERMISSION = "grant_permission"  # params: permission, target(被授權者)
    IDLE = "idle"


@dataclass
class Persona:
    """人格偏好，數值皆介於 0~1。"""

    risk_tolerance: float = 0.5  # 冒險程度
    fairness: float = 0.5  # 重視公平
    greed: float = 0.5  # 重視利益
    sociability: float = 0.5  # 樂於分享 / 交流


@dataclass
class AgentState:
    id: str
    role: str  # farmer | woodcutter | craftsman | merchant
    goal: str  # wealth | safety | influence
    persona: Persona
    inventory: dict[str, float]  # food / wood / tools / money
    health: int = 3
    action_points: int = 2
    # 透過非正式管道得知的資訊（例如別人分享的消息），key -> 內容
    known_info: dict[str, Any] = field(default_factory=dict)
    memory: list[str] = field(default_factory=list)

    @property
    def alive(self) -> bool:
        return self.health > 0


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
class PermissionRequest:
    tick: int
    requester: str
    target: str
    permission: str


@dataclass
class Observation:
    """Agent 在本回合「有權看到」的內容。沒有權限的欄位為 None。"""

    tick: int
    self_state: AgentState
    others: list[dict[str, str]]  # 公開資訊：其他人的 id / role
    prices: dict[str, float] | None
    forecast: dict[str, Any] | None
    permissions: set[str]
    pending_requests: list[PermissionRequest]
    allow_info_sharing: bool


@dataclass
class Market:
    prices: dict[str, float]
    stock: dict[str, float]
    treasury: float


@dataclass
class WorldState:
    tick: int
    agents: dict[str, AgentState]
    market: Market
    # 世界事件：例如 {"food_multiplier": {5: 0.4}} 表示第 5 回合糧食產量 x0.4
    modifiers: dict[str, dict[int, float]] = field(default_factory=dict)
    # 給有權限者看的預報，key 為 info_key
    forecasts: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_requests: list[PermissionRequest] = field(default_factory=list)

    def living_agents(self) -> list[AgentState]:
        return [a for a in self.agents.values() if a.alive]
