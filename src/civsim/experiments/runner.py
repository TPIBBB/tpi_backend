"""實驗控制：同一組條件用不同 seed 重複執行，比較每次天災的結果。

負責人：實驗 / 分析組。
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from civsim.config import SimConfig
from civsim.storage import JsonlRecorder
from civsim.world import SimulationEngine


def run_one(config: SimConfig, out_dir: Path | None = None) -> SimulationEngine:
    recorder = JsonlRecorder(out_dir, meta=asdict(config)) if out_dir else None
    engine = SimulationEngine(config, recorder=recorder)
    engine.run()
    if out_dir:
        (out_dir / "summary.json").write_text(
            json.dumps(engine.summary(), ensure_ascii=False, indent=2), encoding="utf-8")
    return engine


def run_batch(configs: list[SimConfig], repeats: int, out_root: Path) -> Path:
    """每組條件 × 每個 seed × 每次天災一列，輸出 summary.csv。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_dir = out_root / f"batch-{stamp}"
    rows = []
    for config in configs:
        for i in range(repeats):
            cfg = replace(config, seed=config.seed + i)
            engine = run_one(cfg, batch_dir / config.name / f"seed{cfg.seed}")
            for r in engine.reports:
                rows.append({
                    "experiment": config.name, "seed": cfg.seed, "disaster_id": r["disaster_id"],
                    "success": r["success"], "recovered_day": r["recovered_day"],
                    "peak_price": r["peak_price"], "hungry_person_days": r["hungry_person_days"],
                    "deaths": r["deaths"], "band_low": r["band"]["low"], "band_high": r["band"]["high"],
                })

    batch_dir.mkdir(parents=True, exist_ok=True)
    summary = batch_dir / "summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["experiment"])
        writer.writeheader()
        writer.writerows(rows)
    return summary
