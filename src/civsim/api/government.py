"""政府與研究資料的 HTTP 路徑。格式見 docs/api.md。

負責人：digiRunner 整合組 / 前端組（/world/*）。

執行模式是 lockstep（不是 architecture.md 原本的「暫停等待」）：world-api 不自己跑回合迴圈，
政府每送一次決策，世界就前進一天；政府沒送，世界就停著等。

- GET  /runs                                  目前的 run 與狀態
- GET  /runs/{run_id}/government/observation  政府本回合看得到的內容
- POST /runs/{run_id}/government/decisions    提交政府決策，世界跑完這一天
- GET  /runs/{run_id}/government/reflections  等待反思的天災報告與目前的記憶
- POST /runs/{run_id}/government/memory       提交新版記憶，世界調回均衡狀態

反思靠引擎的遠端反思模式（engine.remote_reflection）：評估期最後一天跑完後，引擎先不重置世界，
等 POST memory 送來才重置（docs/api.md 的 D6）。

TODO(前端組)：確認需要的欄位後實作下列路徑（docs/api.md 的 D10）
- GET  /world/disasters         天災時間表與報告
- GET  /world/memory            政府記憶的所有版本
- GET  /world/rules             社會規則
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from civsim.gateway.serialize import observation_to_dict
from civsim.models import GOV_ID, Event
from civsim.world.government import GovernmentActionType, GovernmentDecision

AWAITING_DECISION = "awaiting_decision"
AWAITING_REFLECTION = "awaiting_reflection"
FINISHED = "finished"

MEMORY_RESULTS = {"gov:memory_updated": "updated", "gov:memory_unchanged": "unchanged",
                  "gov:memory_rejected": "rejected"}


def run_status(engine) -> str:
    if engine.pending_reflection is not None:
        return AWAITING_REFLECTION
    if engine.world.tick >= engine.config.total_ticks:
        return FINISHED
    return AWAITING_DECISION


class ApiError(Exception):
    """請求本身有問題（世界不會前進）。由 api/server.py 轉成 {"error", "message"} 的 JSON 回應。"""

    def __init__(self, status_code: int, error: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message


class ActionIn(BaseModel):
    type: str = Field(description="決策類型，例如 release_reserve。未知的類型會被記為拒絕，不是 HTTP 錯誤")
    params: dict[str, Any] = Field(default_factory=dict, description="決策參數，合不合法由引擎檢查")
    reason: str = Field("", description="政府自述理由，只做紀錄")


class DecisionsIn(BaseModel):
    tick: int = Field(description="必須等於目前的 tick，避免重送讓世界多跑一天")
    actions: list[ActionIn] = Field(default_factory=list, description="不想行動就送空陣列")


class MemoryIn(BaseModel):
    memory: str | None = Field(description="完整的新版記憶（Markdown）；null = 不更新")
    reason: str = Field("", description="政府自述理由，目前只做紀錄，不保存")


def _decision_records(events: list[Event]) -> list[dict]:
    """從當天的事件整理出政府決策的結果，格式和 observation 的 recent_decisions 相同。

    不直接讀 engine.cycle_decisions，因為評估期最後一天跑完後世界會重置，那份清單會被清空。
    """
    records = []
    for e in events:
        if e.actor != GOV_ID or e.kind.startswith(("gov:memory", "rule:")):
            continue
        if e.kind == "gov:rejected":
            records.append({**e.payload, "accepted": False, "rejected_reason": e.message})
        elif e.kind.startswith("gov:"):
            p = e.payload
            records.append({
                "tick": e.tick, "type": e.kind[len("gov:"):], "params": p.get("params", {}), "reason": e.message,
                "accepted": True, "result": {k: v for k, v in p.items() if k != "params"},
            })
    return records


def create_government_router(engine, run_id: str, lock: threading.Lock) -> APIRouter:
    """lock 和 /admin/step 共用，同一時間只有一個請求能推進世界。"""
    router = APIRouter(tags=["government"])
    engine.remote_reflection = True  # 政府在 API 的另一端，反思要等 POST memory

    def status() -> str:
        return run_status(engine)

    def next_tick() -> int | None:
        """下一個要決策的 tick；不是 awaiting_decision 時沒有意義，回傳 None。"""
        return engine.world.tick if status() == AWAITING_DECISION else None

    def check(rid: str, expected: str = AWAITING_DECISION) -> None:
        if rid != run_id:
            raise ApiError(404, "run_not_found", f"沒有這個 run：{rid}（目前的 run 是 {run_id}）")
        if status() != expected:
            raise ApiError(409, "wrong_status", f"目前的狀態是 {status()}，這個操作需要 {expected}")

    @router.get("/runs")
    def list_runs():
        """目前的 run。第一版一個 world-api 只跑一個 run（docs/api.md 的 D7）。"""
        return [{
            "run_id": run_id, "config": engine.config.name, "seed": engine.config.seed,
            "status": status(), "tick": engine.world.tick, "total_ticks": engine.config.total_ticks,
        }]

    @router.get("/runs/{rid}/government/observation")
    def observation(rid: str):
        """政府今天看得到的內容。可以重複呼叫，世界不會因此前進。"""
        with lock:
            check(rid)
            engine.begin_tick()
            return {"run_id": run_id, "status": status(), "observation": observation_to_dict(engine.government_observation())}

    @router.post("/runs/{rid}/government/decisions")
    def decisions(rid: str, body: DecisionsIn):
        """送出今天的決策，世界跑完這一天。決策被引擎拒絕不是 HTTP 錯誤，理由在 decisions[].rejected_reason。"""
        with lock:
            check(rid)
            tick = engine.world.tick
            if body.tick != tick:
                raise ApiError(409, "tick_mismatch", f"目前是 tick {tick}，請求的是 tick {body.tick}")

            known = {a.value for a in GovernmentActionType}
            decided, unknown = [], []
            for a in body.actions:
                if a.type in known:
                    decided.append(GovernmentDecision(GovernmentActionType(a.type), a.params, a.reason))
                else:
                    # 和本機模式的 parse_decisions 一樣：未知類型不交給引擎，所以隔天的 recent_decisions 看不到
                    unknown.append({"tick": tick, "type": a.type, "params": a.params, "reason": a.reason,
                                    "accepted": False, "rejected_reason": f"未知的決策類型 {a.type!r}"})

            events = engine.step(decided)
            return {
                "run_id": run_id,
                "tick": tick,
                "decisions": _decision_records(events) + unknown,
                "price": engine.history[-1]["price"],
                "status": status(),
                "next_tick": next_tick(),
            }

    @router.get("/runs/{rid}/government/reflections")
    def reflections(rid: str):
        """一次天災的評估期剛結束：天災報告與目前的記憶。"""
        with lock:
            check(rid, AWAITING_REFLECTION)
            return {"run_id": run_id, "status": status(), "report": engine.pending_reflection, "memory": engine.memory}

    @router.post("/runs/{rid}/government/memory")
    def memory(rid: str, body: MemoryIn):
        """送出新版記憶，世界調回均衡狀態。記憶被拒絕（太長）不是 HTTP 錯誤，看 memory_result。"""
        with lock:
            check(rid, AWAITING_REFLECTION)
            events = engine.submit_memory(body.memory)
            result = next(MEMORY_RESULTS[e.kind] for e in events if e.kind in MEMORY_RESULTS)
            return {
                "run_id": run_id,
                "memory_result": result,
                "memory_version": len(engine.memory_versions) - 1,
                "status": status(),
                "next_tick": next_tick(),
            }

    return router
