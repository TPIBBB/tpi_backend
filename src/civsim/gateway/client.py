"""政府端透過 digiRunner 呼叫 world-api 的 client。

呼叫路徑：政府決策 → HttpWorldClient → digiRunner Gateway → world-api（api/server.py + api/government.py）

digiRunner 負責：路由、身分驗證、流量限制、存取紀錄。社會規則仍由模擬引擎判斷。

負責人：digiRunner 整合組。
TODO(digiRunner 整合組)：api/government.py 的路徑完成後，在這裡加上 observe / submit / reflections / memory，
並實作 GovernmentController 讓引擎可以透過 HTTP 取得政府決策。可用 gateway/serialize.py 轉換格式。
"""

from __future__ import annotations

import os


class HttpWorldClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, run_id: str | None = None):
        import httpx  # 選用相依：pip install -e ".[api]"

        self.base_url = (base_url or os.getenv("DIGIRUNNER_BASE_URL", "http://localhost:8000")).rstrip("/")
        token = token or os.getenv("DIGIRUNNER_CLIENT_TOKEN", "")
        # TODO(digiRunner 整合組)：依 digiRunner 的驗證方式調整 header（OAuth token、API key…）
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if run_id:
            headers["X-Run-Id"] = run_id  # 讓 digiRunner 的存取紀錄能對應到模擬紀錄
        self.http = httpx.Client(base_url=self.base_url, headers=headers, timeout=30)

    def step(self) -> dict:
        r = self.http.post("/admin/step")
        r.raise_for_status()
        return r.json()
