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


PHASES = ("stable", "disaster", "evaluation")  # 穩定期、天災期間、評估期


@dataclass
class GovernmentObservation:
    """政府在本回合看得到的內容（依 11/9 會議）。

    看得到：當下價格、自己的預算與儲備、死亡人數、挨餓人數。看不到平民的庫存，也沒有天災預報。
    欄位由引擎填入，Agent 只讀取；新增欄位請通知 Agent 負責人。
    """

    tick: int
    prices: dict[str, float]
    memory: str | None
    rules: list[str] = field(default_factory=list)
    phase: str = "stable"  # PHASES 之一；天災發生後政府才會知道
    days_since_disaster: int | None = None  # 天災開始後第幾天；穩定期為 None
    budget: float | None = None
    food_reserve: float | None = None
    deaths: int = 0  # 這次天災開始後的死亡人數
    hungry: int | None = None  # 挨餓人數；沒有飢餓機制時為 None
    # 近期決策與被拒絕的理由，每次調回均衡狀態時清空。
    # 格式：{"tick": 回合, "type": 決策類型, "params": {...}, "accepted": bool, "reason": 拒絕理由}
    recent_decisions: list[dict] = field(default_factory=list)
    # 要維持的價格區間，例如 {"food": [4.5, 5.5]}；是否告訴政府還沒定案，不告訴時為 None
    target_price_range: dict[str, list[float]] | None = None


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
