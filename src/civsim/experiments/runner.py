"""實驗控制：同一組條件用不同 seed 重複執行，比較平均值與差異範圍。

負責人：實驗 / 分析組。
"""

from __future__ import annotations

import csv
import statistics
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from civsim.config import SimConfig
from civsim.storage import JsonlRecorder
from civsim.world import SimulationEngine

# 摘要裡要比較的最終指標
SUMMARY_KEYS = ("alive", "wealth_gini", "wealth_mean", "food_gini", "n_authorities", "rejected_actions")


def run_one(config: SimConfig, out_dir: Path | None = None) -> list[dict]:
    recorder = JsonlRecorder(out_dir, meta=asdict(config)) if out_dir else None
    return SimulationEngine(config, recorder=recorder).run()


def run_batch(configs: list[SimConfig], repeats: int, out_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_dir = out_root / f"batch-{stamp}"
    rows = []
    for config in configs:
        finals = []
        for i in range(repeats):
            cfg = replace(config, seed=config.seed + i)
            history = run_one(cfg, batch_dir / config.name / f"seed{cfg.seed}")
            finals.append(history[-1])
        for key in SUMMARY_KEYS:
            values = [f[key] for f in finals]
            rows.append({
                "experiment": config.name,
                "metric": key,
                "mean": round(statistics.mean(values), 4),
                "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
                "min": min(values),
                "max": max(values),
                "n": len(values),
            })

    batch_dir.mkdir(parents=True, exist_ok=True)
    summary = batch_dir / "summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return summary
