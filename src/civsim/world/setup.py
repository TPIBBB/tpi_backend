"""依設定建立初始世界。這個狀態也是每次評估期結束後要調回的「均衡狀態」。"""

from __future__ import annotations

import random

from civsim.config import SimConfig
from civsim.models import Citizen, CitizenType, Government, Market, Persona, WorldState


def create_world(config: SimConfig, rng: random.Random) -> WorldState:
    cc = config.citizens
    citizens: dict[str, Citizen] = {}

    def jitter() -> float:
        return rng.uniform(1 - cc.initial_jitter, 1 + cc.initial_jitter)

    for type_name, count in config.population.items():
        type_ = CitizenType(type_name)
        for _ in range(count):
            cid = f"c{len(citizens):02d}"
            citizens[cid] = Citizen(
                id=cid,
                type=type_,
                persona=Persona(
                    sloth=rng.uniform(0.0, 0.2),
                    greed=rng.random(),
                    risk_tolerance=rng.random(),
                    gluttony=rng.random(),
                ),
                food=round(cc.initial_food.get(type_name, 0.0) * jitter(), 4),
                money=round(cc.initial_money.get(type_name, 0.0) * jitter(), 4),
            )

    # 不服從的人數固定（四捨五入），不是每人各自擲骰，不同 seed 的比例才會一致
    n_defiant = round(len(citizens) * cc.noncompliance_rate)
    for cid in rng.sample(sorted(citizens), n_defiant):
        citizens[cid].persona.complies = False

    gov = Government(budget=config.government.budget, food_reserve=config.government.food_reserve)
    initial_money = sum(c.money for c in citizens.values()) + gov.budget
    market = Market(
        price=config.market.base_price,
        base_price=config.market.base_price,
        initial_money=initial_money or 1.0,
    )
    return WorldState(tick=0, citizens=citizens, government=gov, market=market)
