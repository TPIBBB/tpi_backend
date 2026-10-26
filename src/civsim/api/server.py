"""world-api：把模擬引擎包成 HTTP 服務，註冊到 digiRunner 後面。

啟動：civsim serve --config configs/baseline.yaml
文件：http://localhost:8000/docs

/agents/*  給 Agent 呼叫（應只允許經過 digiRunner 的請求）
/admin/*   給實驗控制器呼叫（推進回合）
/world/*   給前端視覺化讀取（前端在另一個 repo：multi-agent-civilization-sim-frontend）

前端允許的來源由環境變數 CIVSIM_CORS_ORIGINS 設定（逗號分隔），預設為 Vite 開發伺服器。

負責人：digiRunner 整合組 / 前端組（/world/*）。
"""

from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from civsim.gateway.serialize import action_from_dict, observation_to_dict
from civsim.models import Action, Event
from civsim.world import SimulationEngine


def create_app(engine: SimulationEngine) -> FastAPI:
    app = FastAPI(title="civsim world-api")
    origins = os.getenv("CIVSIM_CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])
    submitted: dict[str, list[Action]] = {}
    event_log: list[Event] = []
    state = {"tick_open": False}

    def check_agent(agent_id: str, x_agent_id: str | None) -> None:
        # TODO(digiRunner 整合組)：改為信任 digiRunner 驗證後轉送的身分 header，
        # 並拒絕沒有經過 Gateway 的直接請求
        if x_agent_id != agent_id:
            raise HTTPException(403, "X-Agent-Id 與路徑不符")
        agent = engine.world.agents.get(agent_id)
        if agent is None or not agent.alive:
            raise HTTPException(404, "agent 不存在或已死亡")
        if not state["tick_open"]:
            raise HTTPException(409, "回合尚未開始")

    @app.get("/agents/{agent_id}/observation")
    def observation(agent_id: str, x_agent_id: str | None = Header(default=None)):
        check_agent(agent_id, x_agent_id)
        return observation_to_dict(engine.observe(agent_id))

    @app.post("/agents/{agent_id}/actions")
    def actions(agent_id: str, body: list[dict], x_agent_id: str | None = Header(default=None)):
        check_agent(agent_id, x_agent_id)
        try:
            submitted[agent_id] = [action_from_dict(agent_id, a) for a in body]
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"行動格式錯誤: {e}")
        return {"accepted": len(submitted[agent_id])}

    @app.post("/admin/begin-tick")
    def begin_tick():
        if state["tick_open"]:
            raise HTTPException(409, "回合已開始")
        engine.begin_tick()
        submitted.clear()
        state["tick_open"] = True
        return {"tick": engine.world.tick, "alive": [a.id for a in engine.world.living_agents()]}

    @app.post("/admin/end-tick")
    def end_tick():
        if not state["tick_open"]:
            raise HTTPException(409, "回合尚未開始")
        event_log.extend(engine.step(dict(submitted)))
        state["tick_open"] = False
        return engine.history[-1]

    @app.get("/world/state")
    def world_state():
        w = engine.world
        return {
            "tick": w.tick,
            "market": asdict(w.market),
            "agents": [
                {"id": a.id, "role": a.role, "goal": a.goal, "health": a.health,
                 "inventory": a.inventory, "permissions": sorted(engine.policy.permissions_of(a.id))}
                for a in w.agents.values()
            ],
        }

    @app.get("/world/metrics")
    def world_metrics():
        return engine.history

    @app.get("/world/events")
    def world_events(since_tick: int = 0):
        return [asdict(e) for e in event_log if e.tick >= since_tick]

    return app
