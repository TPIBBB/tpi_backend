from __future__ import annotations

import random

from civsim.agents.base import AgentController
from civsim.agents.government import GovernmentController, LLMGovernment, NoGovernment, make_government
from civsim.agents.rule_based import RuleBasedCitizen
from civsim.config import SimConfig
from civsim.models import WorldState


def build_citizens(world: WorldState, config: SimConfig, cycle: int = 0) -> dict[str, AgentController]:
    """替每位平民建立決策模組。新增平民的決策方式時在這裡註冊。

    每位平民、每個天災週期有自己的亂數源：同一個 seed 的不同組別，第 n 次天災時平民的隨機性完全相同，
    結果的差異才能歸因於政府。
    """
    return {
        cid: RuleBasedCitizen(cid, random.Random(f"{config.seed}:{cycle}:{cid}"), config)
        for cid in sorted(world.citizens)
    }


def build_government(config: SimConfig) -> GovernmentController | None:
    """依 config.government.controller 建立政府；none 表示沒有政府（基準模擬）。"""
    controller = config.government.controller
    if controller == "none":
        return None
    if controller == "llm":
        g = config.government
        return make_government(call_policy=g.call_policy, price_tolerance=g.price_tolerance,
                               max_skip_days=g.max_skip_days)
    raise ValueError(f"未知的 government.controller: {controller}")


__all__ = [
    "AgentController", "GovernmentController", "LLMGovernment", "NoGovernment",
    "RuleBasedCitizen", "build_citizens", "build_government", "make_government",
]
