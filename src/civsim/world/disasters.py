"""天災：事先排好時間表，再依回合觸發。

每次天災週期：[穩定期][天災][評估期] → 調回均衡狀態 → 下一次天災。
不提供天災預報（11/9 會議），所以沒有預警時間，政府和平民都只能從收成和價格察覺。
穩定期長度每次隨機（stable_days ± stable_jitter），有記憶的政府才學不到「第幾天會有天災」。
時間表只由 config 決定，和政府決策、平民的隨機性無關，所有組別都會遇到相同的天災。
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from civsim.config import DisasterConfig
from civsim.models import Event, WorldState


@dataclass
class Disaster:
    id: int  # 第幾次天災，從 1 開始
    kind: str  # 例如 drought
    cycle_start: int  # 這個週期（穩定期）的第一個回合
    start_tick: int  # 天災的第一個回合
    end_tick: int  # 天災的最後一個回合
    window_end: int  # 評估期的最後一回合；這一回合結束後調回均衡狀態
    food_multiplier: float  # 天災期間的收成倍率

    def phase_of(self, tick: int) -> str | None:
        if self.cycle_start <= tick < self.start_tick:
            return "stable"
        if self.start_tick <= tick <= self.end_tick:
            return "disaster"
        if self.end_tick < tick <= self.window_end:
            return "evaluation"
        return None


def build_schedule(config: DisasterConfig) -> list[Disaster]:
    rng = random.Random(f"disasters:{config.schedule_seed}")
    schedule = []
    start = 0
    for i in range(config.count):
        stable = config.stable_days
        if config.stable_jitter:
            stable += rng.randint(-config.stable_jitter, config.stable_jitter)
        stable = max(1, stable)
        multiplier = config.food_multiplier
        if config.multiplier_jitter:
            multiplier += rng.uniform(-config.multiplier_jitter, config.multiplier_jitter)
        d = Disaster(
            id=i + 1,
            kind=config.kind,
            cycle_start=start,
            start_tick=start + stable,
            end_tick=start + stable + config.disaster_days - 1,
            window_end=start + stable + config.disaster_days + config.evaluation_days - 1,
            food_multiplier=round(min(1.0, max(0.0, multiplier)), 4),
        )
        schedule.append(d)
        start = d.window_end + 1
    return schedule


def disaster_at(schedule: list[Disaster], tick: int) -> Disaster | None:
    """這一回合所在的天災週期；超出時間表時回傳 None（例如校準期）。"""
    return next((d for d in schedule if d.phase_of(tick) is not None), None)


def begin_tick_events(world: WorldState, schedule: list[Disaster]) -> list[Event]:
    """回合開始時設定今天的階段與收成倍率，天災開始與結束時產生事件。"""
    d = disaster_at(schedule, world.tick)
    world.disaster_id = d.id if d else None
    world.phase = d.phase_of(world.tick) if d else "stable"
    world.food_multiplier = d.food_multiplier if world.phase == "disaster" else 1.0

    events: list[Event] = []
    if d and world.tick == d.start_tick:
        events.append(Event(world.tick, "world:disaster_start", None, True, asdict(d)))
    if d and world.tick == d.end_tick + 1:
        events.append(Event(world.tick, "world:disaster_end", None, True, {"id": d.id}))
    return events
