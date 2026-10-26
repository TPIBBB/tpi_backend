"""世界事件產生器。事件的「真相」寫入 modifiers，「預報」寫入 forecasts。"""

from __future__ import annotations

import random

from civsim.config import EventConfig
from civsim.models import Event, WorldState

FORECAST_FOOD = "forecast:food"


def generate_events(world: WorldState, config: EventConfig, rng: random.Random) -> list[Event]:
    events: list[Event] = []
    world.forecasts.pop(FORECAST_FOOD, None)

    if rng.random() < config.food_shock_prob:
        target_tick = world.tick + 1
        world.modifiers.setdefault("food_multiplier", {})[target_tick] = config.food_shock_multiplier
        world.forecasts[FORECAST_FOOD] = {
            "tick": target_tick,
            "food_multiplier": config.food_shock_multiplier,
            "text": "明天糧食可能減產",
        }
        events.append(
            Event(
                tick=world.tick,
                kind="world:food_shock_forecast",
                actor=None,
                success=True,
                payload=world.forecasts[FORECAST_FOOD],
            )
        )
    return events


def modifier(world: WorldState, name: str, default: float = 1.0) -> float:
    return world.modifiers.get(name, {}).get(world.tick, default)
