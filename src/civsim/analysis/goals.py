"""判定每次天災是否達成研究目標：1. 市場價格穩定 2. 沒有飢荒。（骨架，尚未接進引擎）

負責人：分析組。接線方式見 docs/architecture.md 的「新方向骨架」。
"""

from __future__ import annotations

from civsim.models import Event


def evaluate_disaster(disaster, history: list[dict], events: list[Event]) -> dict:
    """評估期結束時產生這次天災的報告，引擎會把報告交給政府反思。disaster 是 world/disasters.py 的 Disaster。

    TODO(分析組)：判定標準待大家討論後決定（價格波動多少算平衡、多少人挨餓算飢荒）。
    """
    raise NotImplementedError


def first_sustained(reports: list[dict]) -> int | None:
    """從第幾次天災開始，之後每一次都達標，用來回答「何時可以達到目標」。

    TODO(分析組)：確認「何時達標」要用這個定義，還是其他定義。
    """
    raise NotImplementedError
