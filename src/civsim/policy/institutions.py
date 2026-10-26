"""制度預設：決定一開始誰擁有哪些資訊權限與授權能力。"""

from __future__ import annotations

import random

from civsim.config import InstitutionConfig
from civsim.models import WorldState
from civsim.policy.permissions import PERMISSIONS, PolicyStore, grant_permission_of


def apply_institution(
    world: WorldState, config: InstitutionConfig, rng: random.Random
) -> PolicyStore:
    policy = PolicyStore()
    agent_ids = sorted(world.agents)

    if config.preset == "equal":
        # 資訊與權限平均：人人可讀，無人掌握授權能力
        for agent_id in agent_ids:
            for perm in PERMISSIONS:
                policy.add(agent_id, perm)

    elif config.preset == "hierarchical":
        # 資訊與授權集中於少數菁英
        n_elite = max(1, round(len(agent_ids) * config.elite_fraction))
        for agent_id in rng.sample(agent_ids, n_elite):
            for perm in PERMISSIONS:
                policy.add(agent_id, perm)
                policy.add(agent_id, grant_permission_of(perm))

    elif config.preset == "none":
        pass

    else:
        raise ValueError(f"未知的制度預設: {config.preset}")

    # TODO(實驗 E)：可投票調整制度——把投票結果轉成明確的政策變更，再套用到 PolicyStore
    return policy
