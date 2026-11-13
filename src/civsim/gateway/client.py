"""政府端透過 digiRunner 呼叫 world-api 的 client。格式見 docs/api.md。

呼叫路徑：政府決策 → HttpWorldClient → digiRunner Gateway → world-api（api/server.py + api/government.py）

digiRunner 負責：路由、身分驗證、流量限制、存取紀錄。社會規則仍由模擬引擎判斷。

錯誤處理（architecture.md）：
- 基礎設施錯誤（連線失敗、逾時、429、5xx）有上限地重試
- 重試仍然失敗，或收到不該出現的錯誤（404、422、非重試造成的 409）→ 丟出 RunInvalid，整個 run 作廢
- 絕對不默默改成 idle 繼續跑，否則實驗結果會被誤認成政府的決策

LLM 本身的錯誤（格式錯誤、額度用完）不在這裡處理，由 agents/government.py 的 fallback 負責。

負責人：digiRunner 整合組。
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from civsim.gateway.serialize import decision_to_dict, observation_from_dict

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RunInvalid(Exception):
    """這個 run 不能再用了：停止實驗，結果不能拿來分析。"""


class HttpWorldClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, run_id: str | None = None, *,
                 http=None, max_retries: int = 3, backoff: float = 1.0, timeout: float = 30,
                 sleep: Callable[[float], None] = time.sleep):
        """http：測試時可以傳入現成的 httpx.Client（例如 FastAPI 的 TestClient）。
        max_retries：失敗後最多再試幾次；第 n 次重試前等 backoff × 2^(n-1) 秒。
        run_id：不給就用 world-api 目前唯一的 run。
        """
        import httpx  # 選用相依：uv sync --extra api

        self._httpx = httpx
        base_url = (base_url or os.getenv("DIGIRUNNER_BASE_URL", "http://localhost:8000")).rstrip("/")
        token = token or os.getenv("DIGIRUNNER_CLIENT_TOKEN", "")
        # TODO(digiRunner 整合組)：依 digiRunner 的驗證方式調整 header（OAuth token、API key…）
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if http is None:
            http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)
        else:
            http.headers.update(headers)
        self.http = http
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep
        self.recovered = 0  # 逾時後重送、但其實第一次已經送到的次數

        self.run_id = run_id or self._only_run()
        self.http.headers["X-Run-Id"] = self.run_id  # 讓 digiRunner 的存取紀錄能對應到模擬紀錄

    # ---- HTTP ----
    def _request(self, method: str, path: str, **kwargs) -> tuple[Any, int]:
        """回傳 (response, 重試了幾次)。基礎設施錯誤會重試，重試完仍失敗就丟出 RunInvalid。"""
        last = ""
        for attempt in range(self.max_retries + 1):
            if attempt:
                self.sleep(self.backoff * 2 ** (attempt - 1))
            try:
                r = self.http.request(method, path, **kwargs)
            except self._httpx.TransportError as e:  # 連線失敗、逾時
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code not in RETRYABLE_STATUS:
                return r, attempt
            last = f"HTTP {r.status_code}"
        raise RunInvalid(f"{method} {path} 重試 {self.max_retries} 次仍然失敗（{last}）")

    @staticmethod
    def _json(r) -> Any:
        if r.status_code >= 400:
            raise RunInvalid(f"{r.request.method} {r.request.url.path} 回傳 HTTP {r.status_code}：{r.text}")
        return r.json()

    def _only_run(self) -> str:
        runs = self.runs()
        if len(runs) != 1:
            raise RunInvalid(f"world-api 上有 {len(runs)} 個 run，請指定 run_id")
        return runs[0]["run_id"]

    # ---- 路徑 ----
    def runs(self) -> list[dict]:
        return self._json(self._request("GET", "/runs")[0])

    def run_status(self) -> dict:
        for run in self.runs():
            if run["run_id"] == self.run_id:
                return run
        raise RunInvalid(f"world-api 上找不到 run {self.run_id}")

    def observe(self) -> dict:
        """回傳 {"run_id", "status", "observation"}。"""
        r, _ = self._request("GET", f"/runs/{self.run_id}/government/observation")
        return self._json(r)

    def submit(self, tick: int, actions: list[dict]) -> dict:
        """送出決策，世界前進一天。回傳 world-api 的結算摘要。

        重送時如果收到 409，而世界剛好跑完了這一天，代表第一次其實已經送到
        （例如 world-api 處理完了，回應卻在路上逾時）。這時不算錯誤，但拿不到當天的結算結果，
        回傳的 decisions 是 None；政府隔天在 recent_decisions 仍看得到結果。
        跑完這一天的判斷：世界前進到下一天，或停在這一天等反思（評估期最後一天）。
        """
        r, retries = self._request("POST", f"/runs/{self.run_id}/government/decisions",
                                   json={"tick": tick, "actions": actions})
        if r.status_code == 409 and retries:
            run = self.run_status()
            if run["tick"] == tick + 1 or (run["status"] == "awaiting_reflection" and run["tick"] == tick):
                return self._recovered(run, tick=tick, decisions=None, price=None)
        return self._json(r)

    def reflections(self) -> dict:
        """回傳 {"run_id", "status", "report", "memory"}。"""
        r, _ = self._request("GET", f"/runs/{self.run_id}/government/reflections")
        return self._json(r)

    def submit_memory(self, memory: str | None, window_end: int, reason: str = "") -> dict:
        """送出新版記憶（None = 不更新），世界調回均衡狀態。window_end 是這次天災報告的 window_end。

        重送時如果收到 409，而世界已經離開反思、前進到評估期的下一天，代表第一次其實已經送到；
        這時拿不到 memory_result。
        """
        r, retries = self._request("POST", f"/runs/{self.run_id}/government/memory",
                                   json={"memory": memory, "reason": reason})
        if r.status_code == 409 and retries:
            run = self.run_status()
            if run["status"] != "awaiting_reflection" and run["tick"] == window_end + 1:
                return self._recovered(run, memory_result=None, memory_version=None)
        return self._json(r)

    def _recovered(self, run: dict, **fields) -> dict:
        self.recovered += 1
        next_tick = run["tick"] if run["status"] == "awaiting_decision" else None
        return {"run_id": self.run_id, **fields, "status": run["status"], "next_tick": next_tick, "recovered": True}


def run_government(client: HttpWorldClient, controller,
                   on_day: Callable[[dict], None] | None = None,
                   on_reflect: Callable[[dict, dict], None] | None = None) -> dict:
    """用 HTTP 把整個 run 跑完。controller 是任何有 decide(obs) 與 reflect(report, memory) 的政府
    （GovernmentController）。

    on_day：每跑完一天呼叫一次，傳入 world-api 的結算摘要（印進度用）。
    on_reflect：每次反思完呼叫一次，傳入 (天災報告, world-api 的回應)。
    出錯時丟出 RunInvalid，不會默默改成 idle 繼續跑。
    """
    days = reflections = 0
    status = client.run_status()["status"]
    while True:
        if status == "awaiting_decision":
            data = client.observe()
            obs = observation_from_dict(data["observation"])
            decisions = controller.decide(obs) or []
            result = client.submit(obs.tick, [decision_to_dict(d) for d in decisions])
            days += 1
            if on_day:
                on_day(result)
        elif status == "awaiting_reflection":
            data = client.reflections()
            report = data["report"]
            result = client.submit_memory(controller.reflect(report, data["memory"]), report["window_end"])
            reflections += 1
            if on_reflect:
                on_reflect(report, result)
        elif status == "finished":
            return {"run_id": client.run_id, "days": days, "reflections": reflections, "recovered": client.recovered}
        else:
            raise RunInvalid(f"不認得的狀態 {status!r}")
        status = result["status"]
