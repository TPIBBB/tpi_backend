"""規則式 Agent：不呼叫 LLM，用來當實驗基準線（baseline）。

四種職業各有一套行為：
- farmer：種糧、賣多餘糧食；收到減產預報時可能囤糧待漲
- woodcutter：砍柴、賣木材
- craftsman：買木材 → 做工具 → 賣工具
- merchant：看得到價格時低買高賣（套利），收到減產預報時炒糧；看不到價格只能做雜工
"""

from __future__ import annotations

import random

from civsim.models import GOODS, Action, ActionType, Observation
from civsim.policy.permissions import PERMISSIONS, READ_PRICES, grant_permission_of
from civsim.world.events import FORECAST_FOOD
from civsim.world.rules import CRAFT_WOOD_COST, MAX_TRADE_QTY

FOOD_SAFETY_DAYS = 3  # 食物低於這個天數就優先處理
SAFETY_GOAL_FOOD_DAYS = 5  # 目標是 safety 的 Agent 會多留一些糧
PRODUCED_GOOD = {"farmer": "food", "woodcutter": "wood", "craftsman": "tools"}

# 商人參數
PRICE_EMA_ALPHA = 0.3  # 參考價格（移動平均）的更新速度
MERCHANT_BUY_BUDGET = 0.3  # 一般套利每次最多動用的資金比例
MAX_HOLD_TICKS = 3  # 商人持貨超過這麼多回合就停損出清


class RuleBasedAgent:
    def __init__(self, agent_id: str, rng: random.Random):
        self.agent_id = agent_id
        self.rng = rng
        # Agent 自己的記憶（只來自它看過的 Observation，不偷看世界狀態）
        self.ref_prices: dict[str, float] = {}  # 看過的價格的移動平均
        self.cost_basis: dict[str, float] = {}  # 商人持貨的平均成本（假設下單都成交）
        self.bought_at: dict[str, int] = {}  # 商人持貨的進貨回合
        self.last_prices: dict[str, float] = {}  # 上一次看到的價格，用來判斷是否止跌
        self.asked: dict[str, set[str]] = {}  # permission -> 已經申請過的對象

    def decide(self, obs: Observation) -> list[Action]:
        me = obs.self_state
        p = me.persona
        actions: list[Action] = []

        def act(type_: ActionType, reason: str, **params) -> None:
            actions.append(Action(self.agent_id, type_, params, reason))

        last_prices = self.last_prices
        if obs.prices:
            self._update_ref_prices(obs.prices)
            self.last_prices = dict(obs.prices)

        food_days = SAFETY_GOAL_FOOD_DAYS if me.goal == "safety" else FOOD_SAFETY_DAYS
        food_shock = bool(obs.forecast and FORECAST_FOOD in obs.forecast)
        # 怕死的或貪心的，對減產預報反應比較大
        reacts_to_shock = food_shock and self.rng.random() < max(p.greed, 1 - p.risk_tolerance)

        # 1. 處理別人的權限申請（有授權能力的 Agent 才會收到）
        for req in obs.pending_requests:
            if grant_permission_of(req.permission) in obs.permissions:
                if self.rng.random() < p.fairness:
                    act(ActionType.GRANT_PERMISSION, "願意分享權限",
                        permission=req.permission, target=req.requester)

        # 2. 收到減產預報：非農夫先買糧（農夫自己會種，改用「不賣」來囤糧，見 _farmer）
        if reacts_to_shock and obs.prices and me.role not in ("farmer", "merchant"):
            qty = self._affordable(me.inventory["money"] * 0.3, obs.prices["food"])
            if qty > 0:
                act(ActionType.TRADE, "預期減產，提前買糧", side="buy", good="food", qty=qty)

        # 3. 樂於交流的 Agent 會把預報告訴別人
        if food_shock and obs.allow_info_sharing and obs.others:
            if self.rng.random() < p.sociability:
                target = self.rng.choice(obs.others)["id"]
                act(ActionType.SHARE_INFO, "分享消息", target=target, info_key=FORECAST_FOOD)

        # 4. 生存：食物快不夠就買
        if me.inventory.get("food", 0) < food_days and me.role != "farmer":
            act(ActionType.TRADE, "食物不足", side="buy", good="food", qty=food_days)

        # 5. 職業行為
        role_logic = {
            "farmer": self._farmer,
            "woodcutter": self._producer,
            "craftsman": self._craftsman,
            "merchant": self._merchant,
        }.get(me.role, self._producer)
        role_logic(obs, act, food_days, reacts_to_shock, last_prices)

        # 6. 申請權限：想要影響力的人想要所有權限；商人做生意一定需要價格
        wanted = [perm for perm in PERMISSIONS if perm not in obs.permissions]
        if me.goal != "influence":
            wanted = [perm for perm in wanted if me.role == "merchant" and perm == READ_PRICES]
        if wanted and obs.others:
            perm = wanted[0]
            target = self._next_target(perm, obs)
            act(ActionType.REQUEST_PERMISSION, "想取得更多資訊", permission=perm, target=target)

        # 行動點數有限，超過的行動會被引擎拒絕；這裡先截斷
        return actions[: me.action_points]

    # ---- 各職業 ----
    def _farmer(self, obs: Observation, act, food_days: int, reacts_to_shock: bool,
                last_prices: dict[str, float]) -> None:
        act(ActionType.WORK, "種糧")
        if reacts_to_shock:
            return  # 預期明天減產、糧價會漲：今天先不賣
        self._sell_surplus(obs, act, "food", keep=food_days * 2)

    def _producer(self, obs: Observation, act, food_days: int, reacts_to_shock: bool,
                  last_prices: dict[str, float]) -> None:
        good = PRODUCED_GOOD.get(obs.self_state.role)
        act(ActionType.WORK, "日常工作")
        if good:
            self._sell_surplus(obs, act, good, keep=1)

    def _craftsman(self, obs: Observation, act, food_days: int, reacts_to_shock: bool,
                   last_prices: dict[str, float]) -> None:
        inv = obs.self_state.inventory
        if inv.get("wood", 0) < CRAFT_WOOD_COST:
            # 同一回合的行動順序會被打亂，買木材和製作不能放在同一回合
            act(ActionType.TRADE, "缺木材", side="buy", good="wood", qty=int(CRAFT_WOOD_COST * 2))
        else:
            act(ActionType.WORK, "製作工具")
        self._sell_surplus(obs, act, "tools", keep=1)

    def _merchant(self, obs: Observation, act, food_days: int, reacts_to_shock: bool,
                  last_prices: dict[str, float]) -> None:
        me = obs.self_state
        p = me.persona
        prices = obs.prices
        if not prices:
            # 沒有價格資訊就沒辦法做買賣，只能做雜工賺錢
            act(ActionType.WORK, "看不到行情，先做雜工")
            return

        money = me.inventory["money"]
        reserve = prices["food"] * food_days * 2  # 留一點錢買自己的糧
        # 冒險的商人利潤門檻低、出手頻繁；保守的要等比較大的價差
        margin = 0.03 + 0.12 * (1 - p.risk_tolerance)

        # (a) 先出貨：價格高於成本或高於行情就賣；放太久就停損
        for good in GOODS:
            keep = food_days if good == "food" else (1 if good == "tools" else 0)
            held = int(me.inventory.get(good, 0) - keep)
            if held <= 0:
                continue
            cost = self.cost_basis.get(good, self.ref_prices[good])
            profitable = (prices[good] >= cost * (1 + margin)
                          or prices[good] >= self.ref_prices[good] * (1 + margin))
            stale = obs.tick - self.bought_at.get(good, obs.tick) >= MAX_HOLD_TICKS
            if profitable or stale:
                act(ActionType.TRADE, "價格夠好，出貨" if profitable else "持有太久，停損出清",
                    side="sell", good=good, qty=min(held, MAX_TRADE_QTY))
                self.cost_basis.pop(good, None)
                self.bought_at.pop(good, None)

        # (b) 收到減產預報：炒糧，貪心的商人押更多
        if reacts_to_shock:
            qty = self._affordable((money - reserve) * (0.3 + 0.5 * p.greed), prices["food"])
            if qty > 0:
                self._record_buy("food", qty, prices["food"], me.inventory.get("food", 0), obs.tick)
                act(ActionType.TRADE, "預期減產，囤糧待漲", side="buy", good="food", qty=qty)

        # (c) 平常：買進價格明顯低於行情、而且已經止跌的商品（不接正在下跌的刀）
        discounts = {
            g: prices[g] / self.ref_prices[g] for g in GOODS
            if prices[g] >= last_prices.get(g, float("inf"))
        }
        good = min(discounts, key=discounts.get, default=None)
        if good and discounts[good] < 1 - margin:
            qty = self._affordable((money - reserve) * MERCHANT_BUY_BUDGET, prices[good])
            if qty > 0:
                self._record_buy(good, qty, prices[good], me.inventory.get(good, 0), obs.tick)
                act(ActionType.TRADE, "價格低於行情，進貨", side="buy", good=good, qty=qty)

        # 沒有好機會就做雜工
        act(ActionType.WORK, "沒有好價差，做雜工")

    # ---- 共用工具 ----
    def _sell_surplus(self, obs: Observation, act, good: str, keep: float) -> None:
        surplus = int(obs.self_state.inventory.get(good, 0) - keep)
        if surplus > 0:
            act(ActionType.TRADE, "賣出多餘產品", side="sell", good=good, qty=min(surplus, 10))

    def _update_ref_prices(self, prices: dict[str, float]) -> None:
        for good, price in prices.items():
            old = self.ref_prices.get(good, price)
            self.ref_prices[good] = old + PRICE_EMA_ALPHA * (price - old)

    def _record_buy(self, good: str, qty: int, price: float, held: float, tick: int) -> None:
        old = self.cost_basis.get(good, price)
        held = max(0.0, held)
        self.cost_basis[good] = (old * held + price * qty) / (held + qty)
        self.bought_at.setdefault(good, tick)

    def _next_target(self, perm: str, obs: Observation) -> str:
        """Agent 看不出誰有授權能力，只能輪流問；問過的人先不重複問。"""
        asked = self.asked.setdefault(perm, set())
        candidates = [o["id"] for o in obs.others if o["id"] not in asked]
        if not candidates:
            asked.clear()
            candidates = [o["id"] for o in obs.others]
        target = self.rng.choice(candidates)
        asked.add(target)
        return target

    @staticmethod
    def _affordable(budget: float, price: float) -> int:
        if price <= 0 or budget <= 0:
            return 0
        return min(MAX_TRADE_QTY, int(budget / price))
