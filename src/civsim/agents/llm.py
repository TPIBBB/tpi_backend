"""LLM Agent（骨架）。

負責人：Agent 決策組。
流程：Observation → prompt → LLM 回傳 JSON 行動 → 解析成 Action。
LLM 回傳無法解析時改用 fallback（規則式 Agent），避免整個模擬中斷。

降低成本的建議（見提案「風險與注意事項」）：
- 只在有事件（預報、權限申請）時呼叫 LLM，其餘回合用規則式
- 把 memory 摘要後再放進 prompt
- 記錄 model 名稱、prompt 版本與回應，確保實驗可重現
"""

from __future__ import annotations

import json
import os

from civsim.agents.base import AgentController
from civsim.models import Action, ActionType, Observation

PROMPT_VERSION = "v0"

SYSTEM_PROMPT = """你是虛擬小鎮的一位居民。根據你的目標、人格與看得到的資訊，決定今天的行動。
只回傳 JSON：{"actions": [{"type": "...", "params": {...}, "reason": "..."}]}
可用行動：work, trade(side, good, qty), share_info(target, info_key),
request_permission(permission, target), grant_permission(permission, target), idle"""


def build_prompt(obs: Observation) -> str:
    me = obs.self_state
    return json.dumps(
        {
            "tick": obs.tick,
            "you": {"id": me.id, "role": me.role, "goal": me.goal,
                    "persona": vars(me.persona), "inventory": me.inventory,
                    "health": me.health, "action_points": me.action_points,
                    "recent_memory": me.memory[-5:]},
            "prices": obs.prices,
            "forecast": obs.forecast,
            "permissions": sorted(obs.permissions),
            "pending_requests": [vars(r) for r in obs.pending_requests],
            "others": obs.others,
        },
        ensure_ascii=False,
    )


def parse_actions(agent_id: str, text: str) -> list[Action]:
    data = json.loads(text)
    return [
        Action(agent_id, ActionType(a["type"]), a.get("params", {}), a.get("reason", ""))
        for a in data["actions"]
    ]


class LLMAgent:
    def __init__(self, agent_id: str, fallback: AgentController):
        self.agent_id = agent_id
        self.fallback = fallback
        self.provider = os.getenv("LLM_PROVIDER", "")
        self.model = os.getenv("LLM_MODEL", "")

    def call_llm(self, system: str, user: str) -> str:
        # TODO(Agent 決策組)：選定 LLM 供應商後實作，回傳模型輸出的文字
        raise NotImplementedError("尚未設定 LLM 供應商")

    def decide(self, obs: Observation) -> list[Action]:
        try:
            text = self.call_llm(SYSTEM_PROMPT, build_prompt(obs))
            return parse_actions(self.agent_id, text)
        except (NotImplementedError, ValueError, KeyError):
            return self.fallback.decide(obs)
