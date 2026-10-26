"""每回合的量化指標（對應提案「六、如何判斷模擬結果」）。

負責人：分析組。新增指標時加在 snapshot_metrics() 回傳的 dict 裡即可，
Recorder 與 summary 會自動帶上。
"""

from __future__ import annotations

from civsim.models import Event, WorldState
from civsim.policy import PolicyStore


def gini(values: list[float]) -> float:
    """吉尼係數：0 = 完全平均，1 = 完全集中。"""
    xs = sorted(max(0.0, v) for v in values)
    n, total = len(xs), sum(xs)
    if n == 0 or total == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * total) - (n + 1) / n


def wealth_of(world: WorldState, agent_id: str) -> float:
    """以目前市價計算總財富。"""
    inv = world.agents[agent_id].inventory
    prices = world.market.prices
    return inv.get("money", 0) + sum(inv.get(g, 0) * p for g, p in prices.items())


def snapshot_metrics(world: WorldState, policy: PolicyStore, events: list[Event]) -> dict:
    living = world.living_agents()
    wealth = [wealth_of(world, a.id) for a in living]
    actions = [e for e in events if e.kind.startswith("action:")]
    failed = [e for e in actions if not e.success]

    return {
        "tick": world.tick,
        "alive": len(living),
        # 資源分布
        "wealth_gini": round(gini(wealth), 4),
        "wealth_mean": round(sum(wealth) / len(wealth), 2) if wealth else 0.0,
        "food_gini": round(gini([a.inventory.get("food", 0) for a in living]), 4),
        # 權力集中度
        "n_authorities": len(policy.authorities()),
        "grants_this_tick": sum(1 for e in actions if e.kind == "action:grant_permission" and e.success),
        # 社會穩定性
        "starving": sum(1 for e in events if e.kind == "world:starving"),
        "deaths": sum(1 for e in events if e.kind == "world:death"),
        "rejected_actions": len(failed),
        # 資訊流動
        "info_shares": sum(1 for e in actions if e.kind == "action:share_info" and e.success),
        "prices": dict(world.market.prices),
        # TODO(分析組)：合作效率、個體目標完成率、制度存續
    }
