"""AI 政府的決策與反思。負責人：Agent。（尚未接進引擎）

決策：GovernmentObservation → prompt → LLM 回傳 JSON 決策 → 解析成 GovernmentDecision。
反思：天災報告 + 目前的記憶 → prompt → LLM 回傳新版記憶 Markdown。
政府只能提出決策與新版記憶，兩者都由引擎驗證後才生效。

LLM 呼叫失敗或回應無法解析時，決策改用 fallback（預設是不行動），記憶維持不變，避免整個模擬中斷。
每次呼叫都記錄在 LLMGovernment.calls（含 prompt、回應、token 用量），確保實驗可重現。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Protocol

from civsim.agents.llm_client import LLMCall, LLMClient, ParseError, extract_json, make_client
from civsim.world.government import (
    GOV_ID, GovernmentActionType, GovernmentDecision, GovernmentObservation,
)

GOV_PROMPT_VERSION = "gov-v2"

PHASE_TEXT = {
    "stable": "穩定期（目前沒有天災）",
    "disaster": "天災期間（糧食減產中）",
    "evaluation": "評估期（天災已結束，正在觀察價格能否恢復）",
}

# 給 LLM 看的決策說明。實際可用的決策以引擎的 GovernmentActionType 為準，
# 引擎還沒實作的決策不會出現在 prompt 裡。名稱與參數需要和社會規則負責人確認。
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
    "force_sell": '{"rate": 0 到 1 的比例}，強制有產出的平民把多餘糧食的一部分賣到市場',
    "execute_citizen": '{"target": 平民 id}，處決一位平民',
}

REFLECT_SYSTEM_PROMPT = """你是虛擬小鎮的政府。一次天災的評估期剛結束，請比較你的決策與實際結果，決定要不要更新你的記憶。

記憶是一份 Markdown，下次天災時你會讀到它。社會會被重置回天災前的狀態，你唯一能保留的經驗就是這份記憶，所以只留下次用得上的內容：
- 已被驗證的做法寫在「經驗」，註明依據哪幾次天災
- 只出現過一次的結果可能只是運氣，先放在「待驗證」
- 記下被拒絕的決策與理由，避免下次重犯
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

你的目標：天災發生後，讓糧食（food）價格回到正常的均衡水準，並一直維持到評估期結束。
評估期內價格只要跑出均衡區間一次，這次天災就算失敗。

你要知道的事：
- 一天就是一回合。每天你可以提出零到多個決策，也可以什麼都不做。
- 沒有天災預報。天災發生時你才會知道，請依記憶中過去的經驗判斷怎麼應對。
- 你看得到市場價格、自己的預算與儲備、死亡人數和挨餓人數，看不到平民各自的庫存。
- 平民依固定規則工作與交易，有一部分人不會服從你的政策。
- 你的決策由模擬引擎驗證；資源不足或違反社會規則的決策會被拒絕，拒絕理由會出現在近期決策裡。
- 每次天災的評估期結束後，社會會被重置回天災前的狀態，只有你的記憶會留下來。

請遵守「社會規則」，並參考「你的記憶」裡從過去天災學到的經驗。

可用決策與參數：
{decisions}

只回傳一個 JSON 物件，不要有其他文字：
{{"actions": [{{"type": "...", "params": {{...}}, "reason": "一句話說明理由"}}]}}
不需要行動時回傳 {{"actions": []}}。"""


def build_prompt(obs: GovernmentObservation) -> str:
    """把觀察整理成三段：數字用 JSON，規則用清單，記憶保留原本的 Markdown。"""
    state = {
        "tick": obs.tick,
        "phase": PHASE_TEXT.get(obs.phase, obs.phase),
        "days_since_disaster": obs.days_since_disaster,
        "prices": obs.prices,
        "budget": obs.budget,
        "food_reserve": obs.food_reserve,
        "deaths": obs.deaths,
        "hungry": obs.hungry,
        "target_price_range": obs.target_price_range,
        "recent_decisions": obs.recent_decisions,
    }
    # 沒有的資訊不要給 LLM 看，避免它猜測 None 的意思
    state = {k: v for k, v in state.items() if v is not None}
    rules = "\n".join(f"- {r}" for r in obs.rules) or "（目前沒有社會規則）"
    memory = (obs.memory or "").strip() or "（目前沒有記憶）"
    return (
        f"## 今天的狀態\n```json\n{json.dumps(state, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 社會規則\n{rules}\n\n"
        f"## 你的記憶\n{memory}\n"
    )


def build_reflection_prompt(report: dict, memory: str) -> str:
    return json.dumps({"report": report, "current_memory": memory}, ensure_ascii=False)


# ---- 解析 ----
def parse_decisions(
    text: str, max_decisions: int | None = None
) -> tuple[list[GovernmentDecision], list[str]]:
    """回傳 (決策清單, 被略過的項目說明)。

    個別格式錯誤的決策會被略過，其餘照常執行；整份回應都無法使用時丟出 ParseError。
    這裡只檢查格式，決策是否合法（資源、規則）仍由引擎驗證。
    """
    data = extract_json(text)
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
    if max_decisions is not None and len(decisions) > max_decisions:
        skipped.append(f"一天最多 {max_decisions} 個決策，截掉 {len(decisions) - max_decisions} 個")
        decisions = decisions[:max_decisions]
    return decisions, skipped


def parse_memory(text: str) -> str | None:
    """回傳新版記憶；LLM 表示不修改時回傳 None。"""
    data = extract_json(text)
    if not isinstance(data, dict) or "memory" not in data:
        raise ParseError("回應缺少 memory 欄位")
    memory = data["memory"]
    if memory is not None and not isinstance(memory, str):
        raise ParseError("memory 必須是字串或 null")
    return memory


# ---- 政府 ----
class NoGovernment:
    """完全不介入：LLM 失敗時的預設 fallback，也能用來觀察天災本身的影響。"""

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]:
        return []

    def reflect(self, report: dict, memory: str) -> str | None:
        return None


class LLMGovernment:
    def __init__(
        self,
        client: LLMClient,
        fallback: GovernmentController | None = None,
        max_decisions: int | None = None,  # 一天最多幾個決策；None 表示不限制
    ):
        self.client = client
        self.fallback = fallback or NoGovernment()
        self.max_decisions = max_decisions
        self.calls: list[LLMCall] = []

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]:
        record = self._new_call(obs.tick, "decide", build_prompt(obs))
        try:
            record.response = self._complete(build_system_prompt(), record.prompt, record)
            decisions, record.skipped = parse_decisions(record.response, self.max_decisions)
            return decisions
        except Exception as e:  # 網路、額度、格式錯誤都不能讓模擬中斷
            record.error = f"{type(e).__name__}: {e}"
            record.used_fallback = True
            return self.fallback.decide(obs)

    def reflect(self, report: dict, memory: str) -> str | None:
        prompt = build_reflection_prompt(report, memory)
        record = self._new_call(report.get("window_end", -1), "reflect", prompt)
        try:
            record.response = self._complete(REFLECT_SYSTEM_PROMPT, prompt, record)
            return parse_memory(record.response)
        except Exception as e:
            record.error = f"{type(e).__name__}: {e}"
            return None

    def _complete(self, system: str, user: str, record: LLMCall) -> str:
        try:
            return self.client.complete(system, user)
        finally:  # 回應無法使用時也要記下花了多少 token
            record.usage = getattr(self.client, "last_usage", None)

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
