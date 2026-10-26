"""Agent 端透過 digiRunner 呼叫世界 API 的 client。

呼叫路徑：Agent 決策 → HttpWorldClient → digiRunner Gateway → world-api（api/server.py）

digiRunner 負責：路由、身分驗證、每個 Agent 能呼叫哪些 API、流量限制、存取紀錄。
模擬世界內的權限（read:prices 等）仍由模擬引擎判斷；兩者如何對應見 docs/architecture.md。

負責人：digiRunner 整合組。
"""

from __future__ import annotations

import os

from civsim.agents.base import AgentController
from civsim.gateway.serialize import action_to_dict, observation_from_dict
from civsim.models import Observation


class HttpWorldClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        import httpx  # 選用相依：pip install -e ".[api]"

        self.base_url = (base_url or os.getenv("DIGIRUNNER_BASE_URL", "http://localhost:8000")).rstrip("/")
        token = token or os.getenv("DIGIRUNNER_CLIENT_TOKEN", "")
        # TODO(digiRunner 整合組)：依 digiRunner 的驗證方式調整 header（OAuth token、API key…）
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(base_url=self.base_url, headers=headers, timeout=30)

    def observe(self, agent_id: str) -> Observation:
        r = self.http.get(f"/agents/{agent_id}/observation", headers={"X-Agent-Id": agent_id})
        r.raise_for_status()
        return observation_from_dict(r.json())

    def submit(self, agent_id: str, actions: list) -> dict:
        r = self.http.post(
            f"/agents/{agent_id}/actions",
            json=[action_to_dict(a) for a in actions],
            headers={"X-Agent-Id": agent_id},
        )
        r.raise_for_status()
        return r.json()

    def begin_tick(self) -> dict:
        r = self.http.post("/admin/begin-tick")
        r.raise_for_status()
        return r.json()

    def end_tick(self) -> dict:
        r = self.http.post("/admin/end-tick")
        r.raise_for_status()
        return r.json()


def run_remote(client: HttpWorldClient, controllers: dict[str, AgentController], ticks: int) -> None:
    """以「Agent 經 Gateway 呼叫 API」的方式跑模擬，用來示範 digiRunner 在實際呼叫路徑上。"""
    for _ in range(ticks):
        state = client.begin_tick()
        for agent_id in state["alive"]:
            obs = client.observe(agent_id)
            client.submit(agent_id, controllers[agent_id].decide(obs))
        metrics = client.end_tick()
        print(f"tick {metrics['tick']:>3}  alive={metrics['alive']}  gini={metrics['wealth_gini']}")
