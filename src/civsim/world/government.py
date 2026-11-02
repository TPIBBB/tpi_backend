"""政府的狀態、決策與結算。（骨架，尚未接進引擎）

負責人：模擬引擎組。接線方式見 docs/architecture.md 的「新方向骨架」。

這裡只判斷決策「做不做得到」（預算、庫存、參數）。「應不應該做」由 world/social_rules.py 判斷。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from civsim.models import Event, WorldState

GOV_ID = "gov"


class GovernmentActionType(str, Enum):
    """TODO(模擬引擎組)：和 Agent 決策組確認清單；違反社會邏輯的決策也要列入，才觀察得到違規。"""

    IDLE = "idle"


@dataclass
class Government:
    budget: float
    food_reserve: float


@dataclass
class GovernmentDecision:
    type: GovernmentActionType
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""  # 政府自述理由，只做紀錄，不影響結算


@dataclass
class GovernmentObservation:
    """政府在本回合看得到的內容。

    TODO(模擬引擎組)：和 Agent 決策組確認政府需要看到哪些資訊。
    """

    tick: int
    prices: dict[str, float]
    memory: str | None
    rules: list[str] = field(default_factory=list)


def validate(world: WorldState, decision: GovernmentDecision) -> str | None:
    """回傳 None 表示合法，否則回傳拒絕原因。

    TODO(模擬引擎組)：檢查預算、儲備與參數；LLM 可能回傳任何內容，參數都要檢查。
    """
    raise NotImplementedError


def settle(world: WorldState, decision: GovernmentDecision) -> Event:
    """執行一個已驗證的決策並回傳事件紀錄。

    TODO(模擬引擎組)：實作各決策對市場與平民的影響。
    """
    raise NotImplementedError
