"""事件與狀態紀錄。

- JsonlRecorder：寫到 runs/<實驗名>/，不需要資料庫，預設使用
- PostgresRecorder：寫到 PostgreSQL（db/schema.sql），負責人：資料庫組
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from civsim.models import Event, WorldState


class Recorder(Protocol):
    def record_tick(self, world: WorldState, events: list[Event], metrics: dict) -> None: ...
    def record_disaster(self, report: dict) -> None: ...
    def record_memory(self, version: int, text: str) -> None: ...
    def record_llm_call(self, call: dict) -> None: ...
    def close(self) -> None: ...


class NullRecorder:
    def record_tick(self, world: WorldState, events: list[Event], metrics: dict) -> None:
        pass

    def record_disaster(self, report: dict) -> None:
        pass

    def record_memory(self, version: int, text: str) -> None:
        pass

    def record_llm_call(self, call: dict) -> None:
        pass

    def close(self) -> None:
        pass


class JsonlRecorder:
    """每回合寫一行：events.jsonl / metrics.jsonl / citizens.jsonl；
    每次天災寫一行 disasters.jsonl；每個記憶版本寫一行 memory.jsonl；
    每次呼叫 LLM（政府決策、反思）寫一行 llm_calls.jsonl：prompt、回應、錯誤、token 用量。"""

    def __init__(self, out_dir: str | Path, meta: dict | None = None):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        if meta is not None:
            (self.out_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        self._files = {
            name: (self.out_dir / f"{name}.jsonl").open("w", encoding="utf-8")
            for name in ("events", "metrics", "citizens", "disasters", "memory", "llm_calls")
        }

    def _write(self, name: str, row: dict) -> None:
        self._files[name].write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def record_tick(self, world: WorldState, events: list[Event], metrics: dict) -> None:
        for e in events:
            self._write("events", asdict(e))
        self._write("metrics", metrics)
        for c in world.citizens.values():
            self._write("citizens", {
                "tick": world.tick, "id": c.id, "type": c.type.value, "alive": c.alive,
                "food": round(c.food, 4), "money": round(c.money, 4), "hungry_days": c.hungry_days,
            })

    def record_disaster(self, report: dict) -> None:
        self._write("disasters", report)

    def record_memory(self, version: int, text: str) -> None:
        self._write("memory", {"version": version, "text": text})

    def record_llm_call(self, call: dict) -> None:
        self._write("llm_calls", call)
        self._files["llm_calls"].flush()  # 模擬中途當掉時，已經花掉的呼叫也查得到

    def close(self) -> None:
        for f in self._files.values():
            f.close()


class PostgresRecorder:
    """TODO(資料庫組)：用 psycopg 寫入 db/schema.sql 定義的資料表。"""

    def __init__(self, dsn: str, run_id: str):
        self.dsn = dsn
        self.run_id = run_id
        raise NotImplementedError("PostgresRecorder 尚未實作")

    def record_tick(self, world: WorldState, events: list[Event], metrics: dict) -> None: ...

    def record_disaster(self, report: dict) -> None: ...

    def record_memory(self, version: int, text: str) -> None: ...

    def record_llm_call(self, call: dict) -> None: ...

    def close(self) -> None: ...
