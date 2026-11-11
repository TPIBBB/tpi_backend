"""world-api：把模擬引擎包成 HTTP 服務，註冊到 digiRunner 後面。

啟動：civsim serve --config configs/baseline.yaml
文件：http://localhost:8000/docs

/admin/*   給實驗控制器呼叫（推進回合）
/world/*   給前端視覺化讀取（前端在另一個 repo：TPIBBB/tpi_frontend）

平民在 world-api 內部計算，不走 API。政府的路徑在 api/government.py（API 組實作），
引擎已提供 begin_tick() → government_observation() → step(decisions) 給 API 模式使用。

前端允許的來源由環境變數 CIVSIM_CORS_ORIGINS 設定（逗號分隔），預設為 Vite 開發伺服器。

負責人：digiRunner 整合組 / 前端組（/world/*）。
"""

from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from civsim.models import Event
from civsim.world import SimulationEngine


def create_app(engine: SimulationEngine) -> FastAPI:
    app = FastAPI(title="civsim world-api")
    origins = os.getenv("CIVSIM_CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])
    event_log: list[Event] = []

    @app.post("/admin/step")
    def step():
        """用本機的政府（或沒有政府）推進一回合。"""
        event_log.extend(engine.step())
        return engine.history[-1]

    @app.get("/world/state")
    def world_state():
        w = engine.world
        return {
            "tick": w.tick,
            "phase": w.phase,
            "disaster_id": w.disaster_id,
            "market": {"price": w.market.price, "customary_price": w.market.customary_price,
                       "price_cap": w.market.price_cap, "price_cap_until": w.market.price_cap_until},
            "government": asdict(w.government),
            "band": engine.band.to_dict() if engine.band else None,
            "citizens": [
                {"id": c.id, "type": c.type.value, "alive": c.alive, "food": c.food, "money": c.money,
                 "hungry_days": c.hungry_days}
                for c in w.citizens.values()
            ],
        }

    @app.get("/world/metrics")
    def world_metrics():
        return engine.history

    @app.get("/world/events")
    def world_events(since_tick: int = 0):
        return [asdict(e) for e in event_log if e.tick >= since_tick]

    return app
