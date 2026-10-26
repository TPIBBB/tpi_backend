"""依設定建立初始世界。"""

from __future__ import annotations

import random

from civsim.config import SimConfig
from civsim.models import AgentState, Market, Persona, WorldState

GOAL_CHOICES = ("wealth", "safety", "influence")


def create_world(config: SimConfig, rng: random.Random) -> WorldState:
    agents: dict[str, AgentState] = {}
    index = 0
    for role, count in config.roles.items():
        for _ in range(count):
            agent_id = f"a{index:02d}"
            agents[agent_id] = AgentState(
                id=agent_id,
                role=role,
                goal=rng.choice(GOAL_CHOICES),
                persona=Persona(
                    risk_tolerance=rng.random(),
                    fairness=rng.random(),
                    greed=rng.random(),
                    sociability=rng.random(),
                ),
                inventory=dict(config.initial_inventory),
                action_points=config.action_points,
            )
            index += 1

    market = Market(
        prices=dict(config.market.initial_prices),
        stock=dict(config.market.initial_stock),
        treasury=config.market.treasury,
    )
    return WorldState(tick=0, agents=agents, market=market)
