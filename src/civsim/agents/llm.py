"""LLM 的共用工具：供應商 client、回應解析、呼叫紀錄。

負責人：Agent 決策組。政府的 prompt 與決策在 agents/government.py。

供應商尚未選定：實作一個有 complete(system, user) -> str 的 LLMClient，
在 make_client() 裡依 LLM_PROVIDER 建立即可。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


# ---- 解析 ----
class ParseError(ValueError):
    pass


def _extract_json(text: str) -> Any:
    """容忍常見的格式偏差：```json 區塊、JSON 前後夾雜說明文字。"""
    text = text.strip()
    try:
        return json.loads(text)  # 先試整段，內容裡的 ``` 才不會被誤認成外層的程式碼區塊
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ParseError("回應中找不到 JSON 物件") from None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise ParseError(f"JSON 格式錯誤：{e}") from None


# ---- LLM 供應商 ----
class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class ScriptedClient:
    """不連網的假 LLM：用固定回應或函式產生回應。給測試與流程演練用。"""

    respond: Callable[[str, str], str] | list[str]
    model: str = "scripted"

    def complete(self, system: str, user: str) -> str:
        if callable(self.respond):
            return self.respond(system, user)
        if not self.respond:
            raise RuntimeError("ScriptedClient 的回應已用完")
        return self.respond.pop(0)


def make_client() -> LLMClient | None:
    """依環境變數建立 LLM client；尚未設定供應商時回傳 None（全部改用 fallback）。"""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        return None
    # TODO(Agent 決策組)：選定 LLM 供應商後在這裡建立 client，
    # 讀取 LLM_MODEL / LLM_API_KEY；temperature 建議設 0 以利重現
    raise NotImplementedError(f"尚未實作 LLM 供應商：{provider}")


# ---- 紀錄 ----
@dataclass
class LLMCall:
    """一次決策的紀錄，用來重現與分析實驗。"""

    tick: int
    agent_id: str
    prompt_version: str
    model: str
    used_llm: bool
    trigger: str  # 為什麼呼叫（或不呼叫）LLM
    prompt: str | None = None
    response: str | None = None
    error: str | None = None
    skipped: list[str] = field(default_factory=list)
    used_fallback: bool = False
