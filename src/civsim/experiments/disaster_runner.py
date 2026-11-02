"""比較不同實驗條件在多次天災後的結果。（骨架，尚未接進引擎）

負責人：實驗 / 分析組。接線方式見 docs/architecture.md 的「新方向骨架」。
"""

from __future__ import annotations

from pathlib import Path

from civsim.config import SimConfig


def run_conditions(configs: list[SimConfig], repeats: int, out_root: Path) -> Path:
    """每組條件跑多個 seed，輸出每次天災的達標比例，用來看政府有沒有越來越好。

    TODO(分析組)：一次只改一個條件，例如有記憶 vs 沒有記憶、有規則 vs 沒有規則。
    """
    raise NotImplementedError
