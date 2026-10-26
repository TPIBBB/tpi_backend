"""模擬世界中的權限（研究模型的一部分）。

注意：這裡的權限是「模擬世界的規則」。digiRunner 負責的是現實 API 的存取控制，
兩者的對應方式見 gateway/ 與 docs/architecture.md。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

READ_PRICES = "read:prices"
READ_FORECAST = "read:forecast"

# 可被申請 / 授予的基本權限
PERMISSIONS = (READ_PRICES, READ_FORECAST)


def grant_permission_of(permission: str) -> str:
    """擁有 grant:<perm> 的 Agent 可以把 <perm> 授予他人。"""
    return f"grant:{permission}"


@dataclass
class PolicyStore:
    grants: dict[str, set[str]] = field(default_factory=dict)
    # 授權紀錄：誰授權給誰，用於計算權力集中度
    grant_log: list[tuple[int, str, str, str]] = field(default_factory=list)

    def can(self, agent_id: str, permission: str) -> bool:
        return permission in self.grants.get(agent_id, set())

    def permissions_of(self, agent_id: str) -> set[str]:
        return set(self.grants.get(agent_id, set()))

    def add(self, agent_id: str, permission: str) -> None:
        self.grants.setdefault(agent_id, set()).add(permission)

    def grant(self, tick: int, granter: str, grantee: str, permission: str) -> bool:
        if not self.can(granter, grant_permission_of(permission)):
            return False
        self.add(grantee, permission)
        self.grant_log.append((tick, granter, grantee, permission))
        return True

    def holders_of(self, permission: str) -> list[str]:
        return [a for a, perms in self.grants.items() if permission in perms]

    def authorities(self) -> set[str]:
        """擁有任何授權能力（grant:*）的 Agent。"""
        return {a for a, perms in self.grants.items() if any(p.startswith("grant:") for p in perms)}

    def grants_issued_by(self) -> Counter[str]:
        return Counter(granter for _, granter, _, _ in self.grant_log)
