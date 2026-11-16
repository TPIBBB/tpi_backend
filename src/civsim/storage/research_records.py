"""新方向要保存的紀錄：天災報告、記憶版本、LLM 呼叫。（骨架，尚未接進引擎）

負責人：資料庫組。接線方式見 docs/architecture.md 的「新方向骨架」。
"""

from __future__ import annotations

from typing import Any, Protocol


class ResearchRecorder(Protocol):
    """TODO(資料庫組)：在 JsonlRecorder 實作這些方法，並在 db/schema.sql 新增對應的資料表。"""

    def record_disaster(self, report: dict) -> None: ...

    def record_memory(self, version: int, text: str) -> None:
        """每個版本都要保留，才能分析政府的記憶如何變化。"""
        ...

    def record_call(self, call: Any) -> None:
        """保存 prompt、回應與模型版本，確保實驗可重現。"""
        ...
