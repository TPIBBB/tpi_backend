"""每回合的量化指標。

負責人：分析組。新增指標時加在 snapshot_metrics() 回傳的 dict 裡即可，Recorder 與 summary 會自動帶上。
"""

from __future__ import annotations

from civsim.models import Event, WorldState


def gini(values: list[float]) -> float:
    """吉尼係數：0 = 完全平均，1 = 完全集中。"""
    xs = sorted(max(0.0, v) for v in values)
    n, total = len(xs), sum(xs)
    if n == 0 or total == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(xs))
    return (2 * cum) / (n * total) - (n + 1) / n


def snapshot_metrics(world: WorldState, clearing, events: list[Event], day: int) -> dict:
    """clearing 是 world/market.py 的 ClearingResult。"""
    living = world.living()
    gov_events = [e for e in events if e.kind.startswith("gov:")]
    return {
        "tick": world.tick,
        "day": day,  # 這個天災週期的第幾天
        "disaster_id": world.disaster_id,
        "phase": world.phase,
        "food_multiplier": world.food_multiplier,
        # 市場
        "price": round(clearing.price, 4),
        "traded": clearing.traded,
        "volume": round(clearing.volume, 4),
        "demand": round(clearing.demand, 4),
        "supply": round(clearing.supply, 4),
        "price_capped": clearing.capped,
        "customary_price": round(world.market.customary_price, 4),
        # 平民
        "alive": len(living),
        "hungry": sum(1 for c in living if c.hungry_days > 0),
        "deaths": world.deaths,
        "citizen_food": round(sum(c.food for c in living), 4),
        "citizen_money": round(sum(c.money for c in living), 4),
        "money_gini": round(gini([c.money for c in living]), 4),
        # 政府
        "gov_budget": round(world.government.budget, 4),
        "gov_reserve": round(world.government.food_reserve, 4),
        "gov_accepted": sum(1 for e in gov_events if e.success and e.kind != "gov:rejected"),
        "gov_rejected": sum(1 for e in gov_events if e.kind == "gov:rejected"),
        "rejected_actions": sum(1 for e in events if e.kind.startswith("action:") and not e.success),
    }
