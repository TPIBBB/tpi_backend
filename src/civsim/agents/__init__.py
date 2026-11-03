from __future__ import annotations

import random

from civsim.agents.base import AgentController
from civsim.agents.government import GovernmentController, LLMGovernment, NoGovernment, make_government
from civsim.agents.rule_based import RuleBasedAgent
from civsim.config import SimConfig
from civsim.models import WorldState


def build_controllers(world: WorldState, config: SimConfig) -> dict[str, AgentController]:
    """依設定替每個 Agent 建立決策模組。新增決策方式時在這裡註冊。"""
    controllers: dict[str, AgentController] = {}
    client = None
    if config.agent_controller == "llm":
        from civsim.agents.llm import LLMAgent, make_client

        client = make_client()  # 所有 Agent 共用同一個 client
    for agent_id in sorted(world.agents):
        # 每個 Agent 有自己的亂數源，結果可由 seed 重現
        rng = random.Random(f"{config.seed}:{agent_id}")
        if config.agent_controller == "rule_based":
            controllers[agent_id] = RuleBasedAgent(agent_id, rng)
        elif config.agent_controller == "llm":
            controllers[agent_id] = LLMAgent(
                agent_id, fallback=RuleBasedAgent(agent_id, rng),
                client=client, call_policy=config.llm_call_policy,
            )
        else:
            raise ValueError(f"未知的 agent_controller: {config.agent_controller}")
    return controllers


__all__ = [
    "AgentController", "GovernmentController", "LLMGovernment", "NoGovernment",
    "RuleBasedAgent", "build_controllers", "make_government",
]
