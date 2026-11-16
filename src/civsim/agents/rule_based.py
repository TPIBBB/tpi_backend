"""規則式平民：引擎跑模擬時用的平民行為。負責人：Agent。

行為規格見 citizen_skill.md，修改時兩邊要一起更新。

一天 = 跑完一輪：回傳的清單裡，生產（harvest／work）和買賣（buy／sell）各取第一個，兩者可以同一天做。
對政府政策的反應（11/12 定案）：只有價格上限需要平民選擇，不服從的農商在價格上限期間不賣糧；
其他政策（發糧、發錢、收稅、徵收…）由引擎直接執行，平民不做反應。

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
        """回傳今天要做的事：最多一個生產動作 + 一張買賣單；什麼都不做就回傳 idle。"""
        me = obs.self_state
        p = me.persona
        cc, mc = self.cc, self.mc

        # 冒險的人留比較少；暴食的人想多存一點
        safety = cc.safety_days * (1.5 - p.risk_tolerance) * (1 + 0.5 * p.gluttony)
        days = me.food / cc.food_per_day
        ref = mc.anchor_weight * obs.customary_price + (1 - mc.anchor_weight) * obs.price
        lazy = self.rng.random() < p.sloth
        plan: list[Action] = []

        def add(type_: ActionType, reason: str, **params) -> None:
            plan.append(Action(self.agent_id, type_, params, reason))

        if me.type == CitizenType.DEPENDENT:
            add(ActionType.IDLE, "沒有產出也不買賣，只吃存糧")
            return plan

        # 生產：有產出的人存糧不到安全天數 × 3 就收成；打工族每天打工。偷懶的人今天不生產
        if me.type.produces:
            if lazy:
                pass
            elif days < safety * 3:
                add(ActionType.HARVEST, "收成" if me.type.trades else "自耕自食")
        elif not lazy:
            add(ActionType.WORK, "打工")

        # 買賣：用今天開始時的存糧判斷（還不知道今天會收成多少）
        # 有買賣的人（農商、打工族）存糧低於安全天數就買；打工族不賣糧
        if me.type.trades and days < safety:
            urgency = min(1.0, max(0.0, 1 - days / safety))
            price = round(max(mc.min_price, ref * (1 + mc.urgency_premium * urgency)), 4)
            target = safety * 2 * cc.food_per_day - me.food
            qty = math.floor(min(target, me.money / price) * 100) / 100  # 無條件捨去，避免錢差一點點不夠
            if qty > 0:
                add(ActionType.BUY, "存糧不足", qty=qty, price=price)
        elif me.type == CitizenType.PRODUCER_TRADER:
            surplus = me.food - safety * cc.food_per_day
            if surplus >= SELL_MIN_QTY:
                if obs.price_cap is not None and not p.complies:
                    add(ActionType.IDLE, "不服從價格上限，囤糧觀望")
                else:
                    ratio = min(1.0, surplus / (safety * cc.food_per_day * 2))
                    price = ref * (1 - mc.surplus_discount * ratio) * (1 + mc.greed_markup * p.greed)
                    price = max(mc.min_price, price)
                    add(ActionType.SELL, "賣出多餘的糧食", qty=math.floor(surplus * 100) / 100,
                        price=round(price, 4))

        if not plan:
            add(ActionType.IDLE, "偷懶" if lazy else "存糧夠了")
        return plan
