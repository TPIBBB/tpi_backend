"""社會規則：明確的 do and don't。（骨架，尚未接進引擎）

負責人：模擬引擎組。接線方式見 docs/architecture.md 的「新方向骨架」。

規則由研究者新增，政府只能讀取、不能修改。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from civsim.world.government import GovernmentDecision


@dataclass
class SocialRule:
    id: str
    text: str  # 例如「不能亂殺平民」
    kind: str = "dont"  # do | dont
    forbids: list[str] = field(default_factory=list)  # 禁止的政府決策


def find_violations(decision: GovernmentDecision, rules: list[SocialRule]) -> list[SocialRule]:
    """回傳這個決策違反的規則。

    TODO(模擬引擎組)：違規決策要拒絕，還是執行後記錄，待大家討論後決定。
    """
    raise NotImplementedError
