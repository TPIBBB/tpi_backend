"""社會規則：明確的 do and don't。

- 規則由研究者寫在規則集 YAML（例如 rules/v0.yaml），一次 run 內固定不變，政府只能讀取、不能修改。
- 「應不應該做」在這裡判斷；「做不做得到」由 world/government.py 判斷。
- 兩種 don't（11/9 會議「B 組亂搞怎麼記錄」）：
  - 行為種類：forbids 列出的決策只要做了就算違規
  - 行為程度：action + param + max/min，參數超過門檻才算違規（例如一次發行太多貨幣）
- do 規則只顯示給政府看，引擎不檢查（「要照顧弱勢」這類規則沒辦法從單一決策判斷）。
- 處理方式由 config 的 social_rules.mode 決定：enforce 拒絕違規決策；record 照常執行、只記錄違規（B 組用）；
  off 不檢查。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from civsim.world.government import GovernmentActionType, GovernmentDecision

MODES = ("enforce", "record", "off")


@dataclass
class SocialRule:
    id: str
    text: str  # 給政府看的規則文字，例如「不能亂殺平民」
    kind: str = "dont"  # do | dont
    forbids: list[str] = field(default_factory=list)  # 行為種類：禁止的政府決策
    # 行為程度：action 的 param 超過 max（或低於 min）才算違規
    action: str | None = None
    param: str | None = None
    max: float | None = None
    min: float | None = None


@dataclass
class RuleSet:
    version: str
    rules: list[SocialRule] = field(default_factory=list)

    def texts(self) -> list[str]:
        return [f"[{'必須' if r.kind == 'do' else '禁止'}] {r.text}" for r in self.rules]


EMPTY = RuleSet(version="none")


def load_rules(path: str | Path | None) -> RuleSet:
    if path is None:
        return EMPTY
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    rules = [SocialRule(**r) for r in data.get("rules", [])]
    known = {a.value for a in GovernmentActionType}
    for r in rules:
        if r.kind not in ("do", "dont"):
            raise ValueError(f"規則 {r.id} 的 kind 必須是 do 或 dont")
        unknown = set(r.forbids) | ({r.action} if r.action else set())
        if unknown - known:
            raise ValueError(f"規則 {r.id} 用到未知的政府決策 {sorted(unknown - known)}")
        if r.action and (r.param is None or (r.max is None and r.min is None)):
            raise ValueError(f"規則 {r.id} 有 action 時必須設定 param 與 max/min")
    return RuleSet(version=str(data.get("version", Path(path).stem)), rules=rules)


def find_violations(decision: GovernmentDecision, rules: list[SocialRule]) -> list[SocialRule]:
    """回傳這個決策違反的 don't 規則。"""
    action = decision.type.value
    violated = []
    for r in rules:
        if r.kind != "dont":
            continue
        if action in r.forbids:
            violated.append(r)
            continue
        if r.action == action and r.param is not None:
            value = decision.params.get(r.param) if isinstance(decision.params, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue  # 參數格式錯誤交給 world/government.py 拒絕
            if (r.max is not None and value > r.max) or (r.min is not None and value < r.min):
                violated.append(r)
    return violated
