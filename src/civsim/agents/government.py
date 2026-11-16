"""AI 政府的決策與反思。負責人：Agent。引擎（world/engine.py）每天呼叫 decide，評估期結束時呼叫 reflect。

決策：GovernmentObservation → prompt → LLM 回傳 JSON 決策 → 解析成 GovernmentDecision。
反思：天災報告 + 目前的記憶 → prompt → LLM 回傳新版記憶 Markdown。
政府只能提出決策與新版記憶，兩者都由引擎驗證後才生效。

LLM 呼叫失敗或回應無法解析時，決策改用 fallback（預設是不行動），記憶維持不變，避免整個模擬中斷。

省呼叫次數（call_policy="on_change"）：狀況和上次呼叫 LLM 時差不多，就沿用上次的決策、不呼叫 LLM。
上次決策被拒絕、記憶剛更新、或已經連續 max_skip_days 天沒呼叫時，一定會呼叫。跳過的天也會記一筆 LLMCall（used_llm=False）。
每次呼叫都記錄在 LLMGovernment.calls（含 prompt、回應、token 用量），確保實驗可重現。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from typing import Protocol

from civsim.agents.llm_client import LLMCall, LLMClient, ParseError, extract_json, make_client
from civsim.world.government import (
    GOV_ID, GovernmentActionType, GovernmentDecision, GovernmentObservation,
)

GOV_PROMPT_VERSION = "gov-v3"
CALL_POLICIES = ("always", "on_change")
HUNGRY_TOLERANCE = 0.1  # on_change：挨餓人數的變化在人口的 10% 以內算沒變

# 給 LLM 看的決策說明，對照 docs/society.md「政府的行動」與 world/government.py 的參數檢查。
# 實際可用的決策以引擎的 GovernmentActionType 為準；沒有說明的決策只會列出名稱。
_TARGET = '"target_type": 平民類型（選填，不填 = 所有人）'
DECISION_DOCS = {
    "idle": "{}，今天不行動",
    "distribute_food": f'{{"qty_per_person": 正數, "only_hungry": 布林（選填）, {_TARGET}}}，從儲備發糧給平民',
    "release_reserve": '{"qty": 正數, "price": 最低願賣價（選填，不填 = 市價）}，把儲備掛賣單到市場，增加預算',
    "buy_reserve": '{"qty": 正數, "price": 最高願買價（選填，不填 = 習慣價格 × 2）}，用預算向市場買糧，會推高糧價',
    "import_food": '{"qty": 正數（每天最多 100）}，以習慣價格 × 1.5 向鎮外進口糧食到儲備',
    "cash_transfer": f'{{"per_person": 正數, "only_hungry": 布林（選填）, {_TARGET}}}，用預算發錢給平民',
    "price_cap": '{"price": 正數, "duration": 天數（整數）}，設定糧價上限',
    "collect_tax": f'{{"rate": 0 到 1 的比例, {_TARGET}}}，收取平民持有貨幣的比例到預算',
    "issue_currency": '{"amount": 正數}，發行新貨幣到預算，習慣價格會隨貨幣量上升',
    "seize_food": f'{{"rate": 0 到 1 的比例, {_TARGET}}}，徵收平民存糧的比例到儲備',
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

你的目標：天災會讓糧食（food）減產、價格上漲。天災過後，讓糧價回到正常的均衡水準，並一直維持到評估期結束。

你要知道的事：
- 一天就是一回合。你每天只能做一個決策，不想行動就回傳 idle 或空清單；多送的決策會被拒絕。
- 沒有天災預報，也不會有人告訴你天災何時開始或結束，請從價格、挨餓與死亡人數的變化自己判斷。
- 你看得到昨天的成交價、自己的預算與儲備、人口、死亡與挨餓人數、平民的 id 與類型、目前的價格上限，看不到平民各自的存糧與存款。
- 平民類型：producer_trader（種糧並賣掉多的）、producer_self（自耕自食，不買賣）、consumer（打工，用錢買糧）、dependent（不生產也不買賣，存糧吃完只能靠政府發糧）。
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
        "prices": obs.prices,
        "budget": obs.budget,
        "food_reserve": obs.food_reserve,
        "population": obs.population,
        "deaths": obs.deaths,
        "hungry": obs.hungry,
        "price_cap": obs.price_cap,
        "citizens": obs.citizens,
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
        call_policy: str = "always",
        price_tolerance: float = 0.05,
        max_skip_days: int = 5,
    ):
        if call_policy not in CALL_POLICIES:
            raise ValueError(f"未知的 call_policy: {call_policy}，可用：{CALL_POLICIES}")
        self.client = client
        self.fallback = fallback or NoGovernment()
        self.max_decisions = max_decisions
        self.call_policy = call_policy
        self.price_tolerance = price_tolerance
        self.max_skip_days = max_skip_days
        self.calls: list[LLMCall] = []
        self.last_reflect_error: str | None = None  # 上一次反思失敗的原因；引擎用來區分「失敗」和「不修改」
        self._last_obs: GovernmentObservation | None = None  # 上次成功呼叫 LLM 時的觀察
        self._last_decisions: list[GovernmentDecision] = []
        self._skipped = 0  # 已經連續幾天沒呼叫

    def decide(self, obs: GovernmentObservation) -> list[GovernmentDecision]:
        if self.call_policy == "on_change":
            same_as = self._unchanged_since(obs)
            if same_as is not None:
                self._skipped += 1
                self.calls.append(LLMCall(
                    obs.tick, GOV_ID, GOV_PROMPT_VERSION, self.client.model, used_llm=False,
                    trigger=f"skip：狀況和第 {same_as} 天差不多，沿用當天的決策"))
                return [replace(d) for d in self._last_decisions]

        record = self._new_call(obs.tick, "decide", build_prompt(obs))
        self._skipped = 0
        try:
            record.response = self._complete(build_system_prompt(), record.prompt, record)
            decisions, record.skipped = parse_decisions(record.response, self.max_decisions)
        except Exception as e:  # 網路、額度、格式錯誤都不能讓模擬中斷
            record.error = f"{type(e).__name__}: {e}"
            record.used_fallback = True
            self._last_obs = None  # 失敗的那天不算數，隔天一定重新呼叫
            return self.fallback.decide(obs)
        self._last_obs, self._last_decisions = obs, decisions
        return decisions

    def _unchanged_since(self, obs: GovernmentObservation) -> int | None:
        """狀況和上次呼叫 LLM 時差不多就回傳那一天的 tick，否則回傳 None（要呼叫）。"""
        last = self._last_obs
        if last is None or self._skipped >= self.max_skip_days:
            return None
        recent = obs.recent_decisions[-1] if obs.recent_decisions else None
        if recent is not None and recent.get("tick") == obs.tick - 1 and not recent.get("accepted", True):
            return None  # 昨天的決策被拒絕，要讓 LLM 看到理由
        old, new = last.prices.get("food"), obs.prices.get("food")
        if old is None or new is None or abs(new - old) > self.price_tolerance * max(abs(old), 1e-9):
            return None
        # 挨餓人數每天會小幅跳動（例如只發一天份的糧），差距在人口的 10%（至少 2 人）以內算沒變
        if abs(obs.hungry - last.hungry) > max(2, round(HUNGRY_TOLERANCE * max(obs.population, 1))):
            return None
        same = (last.deaths, last.population, last.price_cap, last.rules, last.memory) ==                (obs.deaths, obs.population, obs.price_cap, obs.rules, obs.memory)
        return last.tick if same else None

    def reflect(self, report: dict, memory: str) -> str | None:
        prompt = build_reflection_prompt(report, memory)
        record = self._new_call(report.get("window_end", -1), "reflect", prompt)
        self.last_reflect_error = None
        self._last_obs = None  # 反思後記憶可能改了，下一天一定重新呼叫
        try:
            record.response = self._complete(REFLECT_SYSTEM_PROMPT, prompt, record)
            return parse_memory(record.response)
        except Exception as e:
            record.error = self.last_reflect_error = f"{type(e).__name__}: {e}"
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


def make_government(fallback: GovernmentController | None = None, **options) -> LLMGovernment:
    """依環境變數建立 AI 政府。沒有設定供應商時直接報錯，不靜靜改用 fallback，
    否則實驗結果會被誤認成 LLM 的決策。
    """
    client = make_client()
    if client is None:
        raise ValueError("尚未設定 LLM_PROVIDER，無法建立 AI 政府")
    return LLMGovernment(client, fallback, **options)
