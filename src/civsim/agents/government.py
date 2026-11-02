"""AI 政府的決策與反思。（骨架，尚未接進引擎）

負責人：Agent 決策組。接線方式見 docs/architecture.md 的「新方向骨架」。

政府只能提出決策與新版記憶，兩者都由引擎驗證後才生效。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from civsim.world.government import GovernmentDecision, GovernmentObservation


class GovernmentController(Protocol):
    """政府的「大腦」，引擎與政府之間唯一的介面。"""

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]: ...

    def reflect(self, report: dict, memory: str) -> str | None:
        """看完一次天災的報告後，回傳新版記憶；不修改時回傳 None。"""
        ...


class LLMGovernment:
    """TODO(Agent 決策組)：可沿用 agents/llm.py 的 LLM 呼叫與解析流程，改寫成政府的 prompt。"""

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]:
        raise NotImplementedError

    def reflect(self, report: dict, memory: str) -> str | None:
        raise NotImplementedError
