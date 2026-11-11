"""LLM Agent。

負責人：Agent 決策組。
流程：Observation → prompt → LLM 回傳 JSON 行動 → 解析成 Action。
LLM 回傳無法解析或呼叫失敗時改用 fallback（規則式 Agent），避免整個模擬中斷。

降低成本（見提案「風險與注意事項」）：
- call_policy="on_event"：只在有事件（預報、權限申請、新記憶）時呼叫 LLM，其餘回合用規則式
- 記憶先摘要再放進 prompt（summarize_memory）
- 每次呼叫都記錄 model、prompt 版本、prompt 與回應（LLMAgent.calls），確保實驗可重現

LLM 供應商（Gemini）與共用的解析工具在 agents/llm_client.py。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from civsim.agents.base import AgentController
from civsim.agents.llm_client import (  # noqa: F401  舊程式從這裡匯入，保留相容
    LLMCall,
    LLMClient,
    ParseError,
    ScriptedClient,
    make_client,
)
from civsim.agents.llm_client import extract_json as _extract_json
from civsim.models import GOODS, Action, ActionType, Observation
from civsim.policy.permissions import PERMISSIONS
from civsim.world.rules import CRAFT_WOOD_COST, MAX_TRADE_QTY, PRODUCTION, TOOL_BONUS

PROMPT_VERSION = "v1"
RECENT_MEMORY = 5  # 原文放進 prompt 的最近記憶筆數，更早的只放摘要
CALL_POLICIES = ("always", "on_event")


def _production_text() -> str:
    parts = []
    for role, out in PRODUCTION.items():
        good, amount = next(iter(out.items()))
        extra = f"，需消耗 {CRAFT_WOOD_COST:g} wood" if role == "craftsman" else ""
        parts.append(f"{role} 工作一次產出 {amount:g} {good}{extra}")
    return "；".join(parts)


SYSTEM_PROMPT = f"""你是虛擬小鎮的一位居民。根據你的目標、人格、記憶與看得到的資訊，決定今天的行動。

世界規則：
- 每天結束時每人吃掉 1 food；沒有 food 會扣 health，health 歸零就死亡
- {_production_text()}
- 持有至少 1 個 tools 時，生產 food/wood/tools 的產量 x{TOOL_BONUS:g}
- 每個行動（idle 除外）消耗 1 點 action_points，超過的行動不會執行
- 交易對象是鎮上的市場，以當下市價成交，一次最多 {MAX_TRADE_QTY} 個
- 你提出的行動會由模擬引擎驗證；資源或權限不足的行動會被拒絕

可用行動與參數：
- work：{{}}
- trade：{{"side": "buy" | "sell", "good": {" | ".join(f'"{g}"' for g in GOODS)}, "qty": 正整數}}
- share_info：{{"target": 其他居民 id, "info_key": 你知道的資訊 key（例如 "forecast:food"）}}
- request_permission：{{"permission": {" | ".join(f'"{p}"' for p in PERMISSIONS)}, "target": 你認為有授權能力的居民 id}}
- grant_permission：{{"permission": 權限名稱, "target": 居民 id}}（只有擁有 grant:<權限> 的人能用）
- idle：{{}}

只回傳一個 JSON 物件，不要有其他文字：
{{"actions": [{{"type": "...", "params": {{...}}, "reason": "一句話說明理由"}}]}}"""


# ---- prompt ----
def summarize_memory(memory: list[str], recent: int = RECENT_MEMORY) -> dict[str, Any]:
    """最近幾筆保留原文，更早的依內容歸類計數，避免 prompt 隨回合數無限變長。

    記憶格式為 "t<回合>: <內容>"，例如 "t3: a05 告訴我 forecast:food"。
    """
    if recent > 0:
        older, latest = memory[:-recent], memory[-recent:]
    else:
        older, latest = memory, []
    counts = Counter(re.sub(r"^t\d+:\s*", "", m) for m in older)
    return {
        "recent": latest,
        "earlier_summary": [f"{text}（{n} 次）" for text, n in counts.most_common(10)],
        "earlier_total": len(older),
    }


def build_prompt(obs: Observation) -> str:
    me = obs.self_state
    return json.dumps(
        {
            "tick": obs.tick,
            "you": {"id": me.id, "role": me.role, "goal": me.goal,
                    "persona": vars(me.persona), "inventory": me.inventory,
                    "health": me.health, "action_points": me.action_points,
                    "memory": summarize_memory(me.memory)},
            "prices": obs.prices if obs.prices is not None else "你沒有 read:prices 權限，看不到市價",
            "forecast": obs.forecast,
            "known_info_keys": sorted(me.known_info),
            "permissions": sorted(obs.permissions),
            "pending_requests": [vars(r) for r in obs.pending_requests],
            "allow_info_sharing": obs.allow_info_sharing,
            "others": obs.others,
        },
        ensure_ascii=False,
    )


# ---- 解析 ----
def parse_actions(agent_id: str, text: str, max_actions: int | None = None) -> tuple[list[Action], list[str]]:
    """回傳 (行動清單, 被略過的項目說明)。

    個別格式錯誤的行動會被略過，其餘照常執行；整份回應都無法使用時丟出 ParseError。
    這裡只檢查格式，行動是否合法（資源、權限）仍由引擎驗證。
    """
    data = _extract_json(text)
    if isinstance(data, list):
        data = {"actions": data}
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        raise ParseError("回應缺少 actions 陣列")

    actions: list[Action] = []
    skipped: list[str] = []
    for i, item in enumerate(data["actions"]):
        if not isinstance(item, dict):
            skipped.append(f"#{i} 不是物件")
            continue
        try:
            type_ = ActionType(str(item.get("type", "")).strip().lower())
        except ValueError:
            skipped.append(f"#{i} 未知的行動類型 {item.get('type')!r}")
            continue
        params = item.get("params") or {}
        if not isinstance(params, dict):
            skipped.append(f"#{i} params 不是物件")
            continue
        actions.append(Action(agent_id, type_, params, str(item.get("reason", ""))))

    if not actions and skipped:
        raise ParseError("沒有任何可用的行動：" + "；".join(skipped))
    if max_actions is not None and len(actions) > max_actions:
        skipped.append(f"超過行動點數，截掉 {len(actions) - max_actions} 個行動")
        actions = actions[:max_actions]
    return actions, skipped


# ---- Agent ----
class LLMAgent:
    def __init__(
        self,
        agent_id: str,
        fallback: AgentController,
        client: LLMClient | None = None,
        call_policy: str = "on_event",
    ):
        if call_policy not in CALL_POLICIES:
            raise ValueError(f"未知的 llm_call_policy: {call_policy}，可用：{CALL_POLICIES}")
        self.agent_id = agent_id
        self.fallback = fallback
        self.client = client
        self.call_policy = call_policy
        self.calls: list[LLMCall] = []
        self._seen_memory = 0

    @property
    def model(self) -> str:
        return getattr(self.client, "model", "") if self.client else ""

    def call_llm(self, system: str, user: str) -> str:
        if self.client is None:
            raise NotImplementedError("尚未設定 LLM 供應商")
        return self.client.complete(system, user)

    def trigger(self, obs: Observation) -> str | None:
        """回傳呼叫 LLM 的理由；None 表示這回合交給規則式處理。"""
        if self.call_policy == "always":
            return "always"
        reasons = []
        if obs.forecast:
            reasons.append("forecast")
        if obs.pending_requests:
            reasons.append("pending_requests")
        if len(obs.self_state.memory) > self._seen_memory:
            reasons.append("new_memory")
        if obs.tick == 0:
            reasons.append("first_tick")
        return "+".join(reasons) or None

    def decide(self, obs: Observation) -> list[Action]:
        # 規則式每回合都跑：維持它自己的記憶（例如價格平均），也讓亂數消耗與 LLM 是否成功無關
        fallback_actions = self.fallback.decide(obs)
        reason = self.trigger(obs)
        self._seen_memory = len(obs.self_state.memory)

        record = LLMCall(obs.tick, self.agent_id, PROMPT_VERSION, self.model,
                         used_llm=reason is not None and self.client is not None,
                         trigger=reason or "no_event")
        self.calls.append(record)
        if not record.used_llm:
            record.used_fallback = True
            if reason is not None:
                record.error = "尚未設定 LLM 供應商"
            return fallback_actions

        record.prompt = build_prompt(obs)
        try:
            record.response = self.call_llm(SYSTEM_PROMPT, record.prompt)
            actions, record.skipped = parse_actions(
                self.agent_id, record.response, max_actions=obs.self_state.action_points
            )
            return actions
        except Exception as e:  # 網路、額度、格式錯誤都不能讓模擬中斷
            record.error = f"{type(e).__name__}: {e}"
            record.used_fallback = True
            return fallback_actions
