"""規則式 Agent：不呼叫 LLM，成本為零、可完全重現，用來當實驗基準線（baseline）。"""

from __future__ import annotations

import random

from civsim.models import Action, ActionType, Observation
from civsim.policy.permissions import PERMISSIONS, grant_permission_of
from civsim.world.rules import CRAFT_WOOD_COST

FOOD_SAFETY_DAYS = 3  # 食物低於這個天數就優先處理
PRODUCED_GOOD = {"farmer": "food", "woodcutter": "wood", "craftsman": "tools"}


class RuleBasedAgent:
    def __init__(self, agent_id: str, rng: random.Random):
        self.agent_id = agent_id
        self.rng = rng

    def decide(self, obs: Observation) -> list[Action]:
        me = obs.self_state
        p = me.persona
        actions: list[Action] = []

        def act(type_: ActionType, reason: str, **params) -> None:
            actions.append(Action(self.agent_id, type_, params, reason))

        # 1. 處理別人的權限申請（有授權能力的 Agent 才會收到）
        for req in obs.pending_requests:
            if grant_permission_of(req.permission) in obs.permissions:
                if self.rng.random() < p.fairness:
                    act(ActionType.GRANT_PERMISSION, "願意分享權限",
                        permission=req.permission, target=req.requester)

        # 2. 收到減產預報：怕死的或貪心的會囤糧
        food_shock = obs.forecast and "forecast:food" in obs.forecast
        if food_shock and obs.prices and me.role != "farmer":
            if self.rng.random() < max(p.greed, 1 - p.risk_tolerance):
                qty = max(1, int(me.inventory["money"] * 0.3 / obs.prices["food"]))
                act(ActionType.TRADE, "預期減產，提前買糧", side="buy", good="food", qty=qty)

        # 3. 樂於交流的 Agent 會把預報告訴別人
        if food_shock and obs.allow_info_sharing and obs.others:
            if self.rng.random() < p.sociability:
                target = self.rng.choice(obs.others)["id"]
                act(ActionType.SHARE_INFO, "分享消息", target=target, info_key="forecast:food")

        # 4. 食物快不夠就買，否則工作
        if me.inventory.get("food", 0) < FOOD_SAFETY_DAYS and me.role != "farmer":
            act(ActionType.TRADE, "食物不足", side="buy", good="food", qty=FOOD_SAFETY_DAYS)
        elif me.role == "craftsman" and me.inventory.get("wood", 0) < CRAFT_WOOD_COST:
            act(ActionType.TRADE, "缺木材", side="buy", good="wood", qty=int(CRAFT_WOOD_COST * 2))
        else:
            act(ActionType.WORK, "日常工作")

        # 5. 賣出多餘產品
        good = PRODUCED_GOOD.get(me.role)
        keep = FOOD_SAFETY_DAYS * 2 if good == "food" else 1
        surplus = int(me.inventory.get(good, 0) - keep) if good else 0
        if surplus > 0:
            act(ActionType.TRADE, "賣出多餘產品", side="sell", good=good, qty=min(surplus, 10))

        # 6. 想要影響力的 Agent 會嘗試申請自己沒有的權限
        if me.goal == "influence":
            missing = [perm for perm in PERMISSIONS if perm not in obs.permissions]
            if missing and obs.others:
                target = self.rng.choice(obs.others)["id"]
                act(ActionType.REQUEST_PERMISSION, "想取得更多資訊",
                    permission=missing[0], target=target)

        # 行動點數有限，超過的行動會被引擎拒絕；這裡先截斷
        return actions[: me.action_points]
