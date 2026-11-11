"""規則式平民：預設行為，讓引擎、市場與均衡價格可以先跑起來。

TODO(Agent 組)：平民的 skill.md、persona 的影響、對政府行動的反應由 Agent 組設計，可以直接改寫這個檔案，
或另外實作一個有 decide(obs) -> list[Action] 的類別，在 agents/__init__.py 的 build_citizens 註冊。
引擎只看回傳的第一個行動（一天一個動作）。

報價方式（市場能不能回到均衡價格取決於這裡，改動時請一起看 docs/society.md）：
- 參考價 = anchor_weight × 習慣價格 + (1 - anchor_weight) × 昨天成交價
- 買價 = 參考價 × (1 + urgency_premium × 急迫度)，存糧越少越急
- 賣價 = 參考價 × (1 - surplus_discount × 存貨比例) × (1 + greed_markup × greed)
"""

from __future__ import annotations

import math
import random

from civsim.config import SimConfig
from civsim.models import Action, ActionType, CitizenType, Observation

SELL_MIN_QTY = 1.0  # 多出來的糧食少於這個量就不賣


class RuleBasedCitizen:
    def __init__(self, citizen_id: str, rng: random.Random, config: SimConfig):
        self.agent_id = citizen_id
        self.rng = rng
        self.cc = config.citizens
        self.mc = config.market

    def decide(self, obs: Observation) -> list[Action]:
        me = obs.self_state
        p = me.persona

        def act(type_: ActionType, reason: str, **params) -> list[Action]:
            return [Action(self.agent_id, type_, params, reason)]

        # 冒險的人留比較少；暴食的人想多存一點
        safety = self.cc.safety_days * (1.5 - p.risk_tolerance) * (1 + 0.5 * p.gluttony)
        days = me.food / self.cc.food_per_day
        ref = self.mc.anchor_weight * obs.customary_price + (1 - self.mc.anchor_weight) * obs.price
        lazy = self.rng.random() < p.sloth

        if me.type == CitizenType.DEPENDENT:
            return act(ActionType.IDLE, "沒有產出也不買賣，只吃存糧")

        if me.type == CitizenType.PRODUCER_SELF:
            if days < safety * 3 and not lazy:
                return act(ActionType.HARVEST, "自耕自食")
            return act(ActionType.IDLE, "存糧夠了" if not lazy else "偷懶")

        if me.type == CitizenType.PRODUCER_TRADER:
            surplus = me.food - safety * self.cc.food_per_day
            if surplus >= SELL_MIN_QTY:
                ratio = min(1.0, surplus / (safety * self.cc.food_per_day * 2))
                price = ref * (1 - self.mc.surplus_discount * ratio) * (1 + self.mc.greed_markup * p.greed)
                price = max(self.mc.min_price, price)
                return act(ActionType.SELL, "賣出多餘的糧食", qty=math.floor(surplus * 100) / 100, price=round(price, 4))
            if lazy:
                return act(ActionType.IDLE, "偷懶")
            return act(ActionType.HARVEST, "收成")

        # CONSUMER：存糧低於安全天數就買，否則打工
        if days < safety:
            urgency = min(1.0, max(0.0, 1 - days / safety))
            price = round(max(self.mc.min_price, ref * (1 + self.mc.urgency_premium * urgency)), 4)
            target = safety * 2 * self.cc.food_per_day - me.food
            qty = min(target, me.money / price)
            qty = math.floor(qty * 100) / 100  # 無條件捨去，避免浮點誤差讓錢差一點點不夠
            if qty > 0:
                return act(ActionType.BUY, "存糧不足", qty=qty, price=price)
        if lazy:
            return act(ActionType.IDLE, "偷懶")
        return act(ActionType.WORK, "打工")
