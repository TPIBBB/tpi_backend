"""天災：事先排好時間表，再依回合觸發。（骨架，尚未接進引擎）

負責人：模擬引擎組。接線方式見 docs/architecture.md 的「新方向骨架」。
"""

from __future__ import annotations

from dataclasses import dataclass

from civsim.models import Event, WorldState


@dataclass
class Disaster:
    id: int  # 第幾次天災，從 1 開始
    kind: str  # 例如 drought / flood / locust
    start_tick: int
    end_tick: int  # 最後一個受影響的回合
    window_end: int  # 評估期的最後一回合，分析組用來判定目標
    warning_tick: int  # 開始出現預報的回合
    food_multiplier: float  # 天災期間的糧食產量倍率


def build_schedule(seed: int, ticks: int) -> list[Disaster]:
    """建立天災時間表。

    TODO(模擬引擎組)：時間表只由 seed 決定、與政府決策無關，不同實驗條件才會遇到相同的天災；
    評估期不能重疊，否則無法分辨結果屬於哪一次天災。
    """
    raise NotImplementedError


def begin_tick_events(world: WorldState, schedule: list[Disaster]) -> list[Event]:
    """回合開始時更新預報、觸發天災，並回傳事件紀錄。

    TODO(模擬引擎組)：取代 world/events.py 的 generate_events，事件種類決定後通知前端組。
    """
    raise NotImplementedError
