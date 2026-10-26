"""Agent 決策模組的共同介面。"""

from __future__ import annotations

from typing import Protocol

from civsim.models import Action, Observation


class AgentController(Protocol):
    """Agent 的「大腦」：看 Observation，提出 Action 清單。

    只能提出行動，不能直接改世界；行動是否成立由模擬引擎驗證。
    """

    agent_id: str

    def decide(self, obs: Observation) -> list[Action]: ...
