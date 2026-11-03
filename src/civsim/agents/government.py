"""AI 政府的決策與反思。（尚未接進引擎）

負責人：Agent 決策組。接線方式見 docs/architecture.md 的「新方向骨架」。

決策：GovernmentObservation → prompt → LLM 回傳 JSON 決策 → 解析成 GovernmentDecision。
反思：天災報告 + 目前的記憶 → prompt → LLM 回傳新版記憶 Markdown。
政府只能提出決策與新版記憶，兩者都由引擎驗證後才生效。

LLM 呼叫失敗或回應無法解析時，決策改用 fallback（預設是不行動），記憶維持不變，避免整個模擬中斷。
每次呼叫都記錄在 LLMGovernment.calls，確保實驗可重現。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from typing import Protocol

from civsim.agents.llm import LLMCall, LLMClient, ParseError, _extract_json, make_client
from civsim.world.government import (
    GOV_ID, GovernmentActionType, GovernmentDecision, GovernmentObservation,
)

GOV_PROMPT_VERSION = "gov-v1"

# 給 LLM 看的決策說明。實際可用的決策以模擬引擎組的 GovernmentActionType 為準，
# 引擎還沒實作的決策不會出現在 prompt 裡。名稱與參數需要和模擬引擎組確認。
DECISION_DOCS = {
    "idle": "{}，這回合不行動",
    "distribute_food": '{"qty_per_person": 正數, "only_hungry": 布林}，從儲備發糧給平民',
    "release_reserve": '{"qty": 正數}，把儲備賣到市場，壓低糧價並增加預算',
    "buy_reserve": '{"qty": 正數}，用預算向市場買糧，會推高糧價',
    "import_food": '{"qty": 正數}，向鎮外進口糧食到儲備，單價比市價高',
    "cash_transfer": '{"per_person": 正數}，用預算發錢給每位平民',
    "price_cap": '{"good": 商品名稱, "price": 正數, "duration": 回合數}，設定價格上限',
    "collect_tax": '{"rate": 0 到 1 的比例}，向每位平民收取持有貨幣的比例',
    "issue_currency": '{"amount": 正數}，發行新貨幣到預算，物價水準會上升',
    "seize_food": '{"rate": 0 到 1 的比例}，徵收每位平民持有糧食的比例到儲備',
    "execute_citizen": '{"target": 平民 id}，處決一位平民',
}

REFLECT_SYSTEM_PROMPT = """你是虛擬小鎮的政府。一次天災剛結束，請比較你的決策與實際結果，決定要不要更新你的記憶。

記憶是一份 Markdown，下次決策時你會讀到它。你唯一能保留的經驗就是這份記憶，所以只留下次用得上的內容：
- 已被驗證的做法寫在「經驗」，註明依據哪幾次天災
- 只出現過一次的結果可能只是運氣，先放在「待驗證」
- 發現舊內容有誤就修改或刪除
- 社會規則不屬於記憶：記憶不能改變規則，也不能用來繞過規則

只回傳一個 JSON 物件，不要有其他文字。memory 是完整的新版記憶，不需要修改時填 null：
{"memory": "完整的 Markdown" | null, "reason": "一句話說明理由"}"""


class GovernmentController(Protocol):
    """政府的「大腦」，引擎與政府之間唯一的介面。"""

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]: ...

    def reflect(self, report: dict, memory: str) -> str | None:
        """看完一次天災的報告後，回傳新版記憶；不修改時回傳 None。"""
        ...


# ---- prompt ----
def build_system_prompt(action_types: Iterable[GovernmentActionType] = GovernmentActionType) -> str:
    # 沒有說明的決策也要列出名稱，引擎新增決策時政府才用得到
    decisions = "\n".join(f"- {a.value}：{DECISION_DOCS.get(a.value, '參數待補')}" for a in action_types)
    return f"""你是虛擬小鎮的政府，負責治理一群平民並應對天災。

你的兩個目標：
1. 市場穩定：市場價格維持平衡，不要大幅波動
2. 沒有飢荒：就算天災來臨，也不會有人挨餓或餓死

平民依固定規則工作與交易，不會聽從你的指令，只會受到你的決策與市場變化影響。
你提出的決策會由模擬引擎驗證；資源不足或違反社會規則的決策可能被拒絕。
請遵守 rules 裡的社會規則，並參考 memory 裡你從過去天災學到的經驗。

可用決策與參數：
{decisions}

只回傳一個 JSON 物件，不要有其他文字：
{{"actions": [{{"type": "...", "params": {{...}}, "reason": "一句話說明理由"}}]}}"""


def build_prompt(obs: GovernmentObservation) -> str:
    return json.dumps(asdict(obs), ensure_ascii=False)


def build_reflection_prompt(report: dict, memory: str) -> str:
    return json.dumps({"report": report, "current_memory": memory}, ensure_ascii=False)


# ---- 解析 ----
def parse_decisions(text: str) -> tuple[list[GovernmentDecision], list[str]]:
    """回傳 (決策清單, 被略過的項目說明)。

    個別格式錯誤的決策會被略過，其餘照常執行；整份回應都無法使用時丟出 ParseError。
    這裡只檢查格式，決策是否合法（資源、規則）仍由引擎驗證。
    """
    data = _extract_json(text)
    if isinstance(data, list):
        data = {"actions": data}
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        raise ParseError("回應缺少 actions 陣列")

    decisions: list[GovernmentDecision] = []
    skipped: list[str] = []
    for i, item in enumerate(data["actions"]):
        if not isinstance(item, dict):
            skipped.append(f"#{i} 不是物件")
            continue
        try:
            type_ = GovernmentActionType(str(item.get("type", "")).strip().lower())
        except ValueError:
            skipped.append(f"#{i} 未知的決策類型 {item.get('type')!r}")
            continue
        params = item.get("params") or {}
        if not isinstance(params, dict):
            skipped.append(f"#{i} params 不是物件")
            continue
        decisions.append(GovernmentDecision(type_, params, str(item.get("reason", ""))))

    if not decisions and skipped:
        raise ParseError("沒有任何可用的決策：" + "；".join(skipped))
    return decisions, skipped


def parse_memory(text: str) -> str | None:
    """回傳新版記憶；LLM 表示不修改時回傳 None。"""
    data = _extract_json(text)
    if not isinstance(data, dict) or "memory" not in data:
        raise ParseError("回應缺少 memory 欄位")
    memory = data["memory"]
    if memory is not None and not isinstance(memory, str):
        raise ParseError("memory 必須是字串或 null")
    return memory


# ---- 政府 ----
class NoGovernment:
    """完全不介入：LLM 失敗時的預設 fallback，也是衡量天災本身影響的對照組。"""

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]:
        return []

    def reflect(self, report: dict, memory: str) -> str | None:
        return None


class LLMGovernment:
    """TODO(Agent 決策組)：observation 有天災與預報欄位後，加上只在天災前後呼叫 LLM 的選項以降低成本。"""

    def __init__(self, client: LLMClient, fallback: GovernmentController | None = None):
        self.client = client
        self.fallback = fallback or NoGovernment()
        self.calls: list[LLMCall] = []

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]:
        record = self._new_call(obs.tick, "decide", build_prompt(obs))
        try:
            record.response = self.client.complete(build_system_prompt(), record.prompt)
            decisions, record.skipped = parse_decisions(record.response)
            return decisions
        except Exception as e:  # 網路、額度、格式錯誤都不能讓模擬中斷
            record.error = f"{type(e).__name__}: {e}"
            record.used_fallback = True
            return self.fallback.decide(obs)

    def reflect(self, report: dict, memory: str) -> str | None:
        prompt = build_reflection_prompt(report, memory)
        record = self._new_call(report.get("window_end", -1), "reflect", prompt)
        try:
            record.response = self.client.complete(REFLECT_SYSTEM_PROMPT, prompt)
            return parse_memory(record.response)
        except Exception as e:
            record.error = f"{type(e).__name__}: {e}"
            return None

    def _new_call(self, tick: int, trigger: str, prompt: str) -> LLMCall:
        record = LLMCall(tick, GOV_ID, GOV_PROMPT_VERSION, self.client.model,
                         used_llm=True, trigger=trigger, prompt=prompt)
        self.calls.append(record)
        return record


def make_government(fallback: GovernmentController | None = None) -> LLMGovernment:
    """依環境變數建立 AI 政府。沒有設定供應商時直接報錯，不靜靜改用 fallback，
    否則實驗結果會被誤認成 LLM 的決策。
    """
    client = make_client()
    if client is None:
        raise ValueError("尚未設定 LLM_PROVIDER，無法建立 AI 政府")
    return LLMGovernment(client, fallback)
