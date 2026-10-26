"""行動驗證與結算。Agent 說什麼都不算數，只有通過這裡的行動才會改變世界。"""

from __future__ import annotations

from dataclasses import dataclass

from civsim.models import GOODS, Action, ActionType, Event, PermissionRequest, WorldState
from civsim.policy.permissions import PERMISSIONS, PolicyStore, grant_permission_of
from civsim.world.events import modifier

# 每種職業工作一次的產出
PRODUCTION = {
    "farmer": {"food": 3.0},
    "woodcutter": {"wood": 3.0},
    "craftsman": {"tools": 1.0},  # 需消耗 wood
    "merchant": {"money": 4.0},
}
CRAFT_WOOD_COST = 2.0
TOOL_BONUS = 1.5  # 擁有工具時產量加成
MAX_TRADE_QTY = 20


@dataclass
class TickContext:
    """單一回合內的暫存資料（市場淨需求等）。"""

    demand: dict[str, float]
    allow_info_sharing: bool


def validate(world: WorldState, policy: PolicyStore, ctx: TickContext, action: Action) -> str | None:
    """回傳 None 表示合法，否則回傳拒絕原因。"""
    agent = world.agents.get(action.agent_id)
    if agent is None or not agent.alive:
        return "agent 不存在或已死亡"
    if action.type == ActionType.IDLE:
        return None
    if agent.action_points <= 0:
        return "行動點數不足"

    p = action.params
    if action.type == ActionType.WORK:
        if agent.role == "craftsman" and agent.inventory.get("wood", 0) < CRAFT_WOOD_COST:
            return "木材不足，無法製作工具"
        return None

    if action.type == ActionType.TRADE:
        good, side = p.get("good"), p.get("side")
        try:
            qty = int(p.get("qty", 0))
        except (TypeError, ValueError):
            return "qty 必須是整數"
        if good not in GOODS or side not in ("buy", "sell") or not 0 < qty <= MAX_TRADE_QTY:
            return "交易參數不合法"
        cost = world.market.prices[good] * qty
        if side == "buy":
            if agent.inventory["money"] < cost:
                return "貨幣不足"
            if world.market.stock.get(good, 0) < qty:
                return "市場庫存不足"
        else:
            if agent.inventory.get(good, 0) < qty:
                return "庫存不足"
            if world.market.treasury < cost:
                return "市場資金不足"
        return None

    if action.type == ActionType.SHARE_INFO:
        if not ctx.allow_info_sharing:
            return "本實驗不允許分享資訊"
        target = world.agents.get(p.get("target", ""))
        if target is None or not target.alive or target.id == agent.id:
            return "分享對象不合法"
        if p.get("info_key") not in agent.known_info:
            return "不知道這則資訊，無法分享"
        return None

    if action.type == ActionType.REQUEST_PERMISSION:
        perm, target = p.get("permission"), p.get("target")
        if perm not in PERMISSIONS:
            return "未知的權限"
        if policy.can(agent.id, perm):
            return "已擁有此權限"
        if not policy.can(target, grant_permission_of(perm)):
            return "對象沒有授權能力"
        return None

    if action.type == ActionType.GRANT_PERMISSION:
        perm, target = p.get("permission"), p.get("target")
        if target not in world.agents:
            return "授權對象不存在"
        if not policy.can(agent.id, grant_permission_of(perm)):
            return "沒有授權能力"
        return None

    return f"未知的行動類型 {action.type}"


def settle(world: WorldState, policy: PolicyStore, ctx: TickContext, action: Action) -> Event:
    """執行一個已驗證的行動並回傳事件紀錄。"""
    agent = world.agents[action.agent_id]
    p = action.params
    payload: dict = {"params": p}

    if action.type != ActionType.IDLE:
        agent.action_points -= 1

    if action.type == ActionType.WORK:
        output: dict[str, float] = {}
        if agent.role == "craftsman":
            agent.inventory["wood"] -= CRAFT_WOOD_COST
        for good, amount in PRODUCTION.get(agent.role, {}).items():
            if good != "money" and agent.inventory.get("tools", 0) >= 1:
                amount *= TOOL_BONUS
            if good == "food":
                amount *= modifier(world, "food_multiplier")
            agent.inventory[good] = agent.inventory.get(good, 0) + amount
            output[good] = amount
        payload["output"] = output

    elif action.type == ActionType.TRADE:
        good, side, qty = p["good"], p["side"], int(p["qty"])
        price = world.market.prices[good]
        sign = 1 if side == "buy" else -1
        agent.inventory[good] = agent.inventory.get(good, 0) + sign * qty
        agent.inventory["money"] -= sign * price * qty
        world.market.stock[good] -= sign * qty
        world.market.treasury += sign * price * qty
        ctx.demand[good] = ctx.demand.get(good, 0) + sign * qty
        payload.update(price=price, total=price * qty)

    elif action.type == ActionType.SHARE_INFO:
        target = world.agents[p["target"]]
        key = p["info_key"]
        target.known_info[key] = agent.known_info[key]
        target.memory.append(f"t{world.tick}: {agent.id} 告訴我 {key}")

    elif action.type == ActionType.REQUEST_PERMISSION:
        world.pending_requests.append(
            PermissionRequest(world.tick, agent.id, p["target"], p["permission"])
        )

    elif action.type == ActionType.GRANT_PERMISSION:
        perm, grantee = p["permission"], p["target"]
        policy.grant(world.tick, agent.id, grantee, perm)
        world.pending_requests = [
            r for r in world.pending_requests
            if not (r.requester == grantee and r.permission == perm)
        ]
        world.agents[grantee].memory.append(f"t{world.tick}: {agent.id} 授予我 {perm}")

    return Event(world.tick, f"action:{action.type.value}", agent.id, True, payload, action.reason)


def end_of_tick_upkeep(world: WorldState, action_points: int) -> list[Event]:
    """每回合結束：每人消耗 1 單位食物，沒食物就扣健康。"""
    events: list[Event] = []
    for agent in world.living_agents():
        if agent.inventory.get("food", 0) >= 1:
            agent.inventory["food"] -= 1
        else:
            agent.health -= 1
            events.append(Event(world.tick, "world:starving", agent.id, True, {"health": agent.health}))
            if not agent.alive:
                events.append(Event(world.tick, "world:death", agent.id, True))
        agent.action_points = action_points
    return events
