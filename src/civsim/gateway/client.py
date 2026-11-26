"""政府端透過 digiRunner 呼叫 world-api 的 client。格式見 docs/api.md。

呼叫路徑：政府決策 → HttpWorldClient → digiRunner Gateway → world-api（api/server.py + api/government.py）

digiRunner 負責：路由、身分驗證、流量限制、存取紀錄。社會規則仍由模擬引擎判斷。

錯誤處理（architecture.md）：
- 基礎設施錯誤（連線失敗、逾時、429、5xx）有上限地重試
- 重試仍然失敗，或收到不該出現的錯誤（404、422、非重試造成的 409）→ 丟出 RunInvalid，整個 run 作廢
- 絕對不默默改成 idle 繼續跑，否則實驗結果會被誤認成政府的決策

身分驗證（digiRunner 的 Client Credentials，設定方式見 docs/digirunner_setup.md）：
- 直連 world-api 時不需要驗證，永遠不會收到 401，也不會去申請 token
- 經過 digiRunner 時，收到 401 就用 DIGIRUNNER_CLIENT_ID / DIGIRUNNER_CLIENT_SECRET 向 /oauth/token 換 token，
  再送一次。一開始還沒有 token、或 token 過期（預設 1 天），都走同一條路
- 帳密被拒絕、換到的 token 仍被拒絕、或收到 403（這個 client 沒有權限呼叫這條路徑）→ run 作廢
- token 和密碼都不會出現在錯誤訊息裡

LLM 本身的錯誤（格式錯誤、額度用完）不在這裡處理，由 agents/government.py 的 fallback 負責。

負責人：digiRunner 整合組。
"""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from civsim.gateway.serialize import decision_to_dict, observation_from_dict

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
TOKEN_PATH = "/oauth/token"


class RunInvalid(Exception):
    """這個 run 不能再用了：停止實驗，結果不能拿來分析。"""


def basic_credentials(client_id: str, client_secret: str) -> str:
    """digiRunner 申請 token 時 Basic 驗證的值：Base64(帳號 + ":" + Base64(密碼))。

    注意密碼要先自己 Base64 一次，和一般的 HTTP Basic 不同（digiRunner 文件的 Client Credentials Mode）。
    """
    def b64(s: str) -> str:
        return base64.b64encode(s.encode("utf-8")).decode("ascii")

    return b64(f"{client_id}:{b64(client_secret)}")


@dataclass(frozen=True)
class ClientCredentials:
    """digiRunner 的 client 帳密。密碼不會出現在 repr() 裡，避免被誤印出來。"""

    client_id: str
    client_secret: str = field(repr=False)

    @classmethod
    def from_env(cls) -> ClientCredentials | None:
        """讀 DIGIRUNNER_CLIENT_ID / DIGIRUNNER_CLIENT_SECRET（civsim 啟動時會讀入 .env）；缺一個就回傳 None。"""
        client_id = os.getenv("DIGIRUNNER_CLIENT_ID", "").strip()
        client_secret = os.getenv("DIGIRUNNER_CLIENT_SECRET", "").strip()
        return cls(client_id, client_secret) if client_id and client_secret else None


class HttpWorldClient:
    def __init__(self, base_url: str | None = None, *, run_id: str | None = None,
                 credentials: ClientCredentials | None = None,
                 http=None, max_retries: int = 3, backoff: float = 1.0, timeout: float = 30,
                 sleep: Callable[[float], None] = time.sleep):
        """除了 base_url，其他參數都只能用名字指定（例如 run_id=...），避免參數順序改變時被悄悄傳錯。

        http：測試時可以傳入現成的 httpx.Client（例如 FastAPI 的 TestClient）。
        max_retries：失敗後最多再試幾次；第 n 次重試前等 backoff × 2^(n-1) 秒。
        run_id：不給就用 world-api 目前唯一的 run。
        credentials：digiRunner 的 client 帳密，不給就讀環境變數；直連 world-api 時用不到。
        """
        import httpx  # 選用相依：uv sync --extra api

        self._httpx = httpx
        base_url = (base_url or os.getenv("DIGIRUNNER_BASE_URL", "http://localhost:8000")).rstrip("/")
        self._credentials = credentials or ClientCredentials.from_env()
        self._token = ""  # 第一次收到 401 時才去申請
        if http is None:
            http = httpx.Client(base_url=base_url, timeout=timeout)
        self.http = http
        self.max_retries = max_retries
        self.backoff = backoff
        self.sleep = sleep
        self.recovered = 0  # 逾時後重送、但其實第一次已經送到的次數
        self.token_requests = 0  # 向 digiRunner 申請 token 的次數

        self.run_id = run_id or self._only_run()
        self.http.headers["X-Run-Id"] = self.run_id  # 讓 digiRunner 的存取紀錄能對應到模擬紀錄

    @property
    def client_id(self) -> str:
        return self._credentials.client_id if self._credentials else ""

    # ---- HTTP ----
    def _send(self, method: str, path: str, *, auth: bool = True, **kwargs) -> tuple[Any, int]:
        """送一次請求，基礎設施錯誤會重試。回傳 (response, 重試了幾次)，重試完仍失敗就丟出 RunInvalid。"""
        headers = dict(kwargs.pop("headers", None) or {})
        last = ""
        for attempt in range(self.max_retries + 1):
            if attempt:
                self.sleep(self.backoff * 2 ** (attempt - 1))
            if auth and self._token:
                headers["Authorization"] = f"Bearer {self._token}"  # 每次重新帶，token 可能剛換過
            try:
                r = self.http.request(method, path, headers=headers, **kwargs)
            except self._httpx.TransportError as e:  # 連線失敗、逾時
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code not in RETRYABLE_STATUS:
                return r, attempt
            last = f"HTTP {r.status_code}"
        raise RunInvalid(f"{method} {path} 重試 {self.max_retries} 次仍然失敗（{last}）")

    def _request(self, method: str, path: str, **kwargs) -> tuple[Any, int]:
        """回傳 (response, 重試了幾次)。收到 401 會換 token 再送一次；403 代表沒有權限，run 作廢。

        換 token 前後的重試次數會加總：只要曾經重送，submit() 就會用 409 判斷第一次是否其實已經送到。
        """
        r, retries = self._send(method, path, **kwargs)
        if r.status_code == 401:
            self._refresh_token()
            r, more = self._send(method, path, **kwargs)
            retries += more
            if r.status_code == 401:
                raise RunInvalid(f"{method} {path}：剛向 digiRunner 換到的 token 仍被拒絕（401）")
        if r.status_code == 403:
            who = self.client_id or "（未設定 client）"
            raise RunInvalid(f"{method} {path}：digiRunner 拒絕 client {who} 呼叫這條路徑（403），"
                             "請檢查這個 client 被授權的群組")
        return r, retries

    def _refresh_token(self) -> None:
        """用 client 帳密向 digiRunner 換新的 access token。"""
        creds = self._credentials
        if creds is None:
            raise RunInvalid("digiRunner 要求身分驗證（401），但沒有設定 DIGIRUNNER_CLIENT_ID / DIGIRUNNER_CLIENT_SECRET")
        self.token_requests += 1
        r, _ = self._send("POST", TOKEN_PATH, auth=False,
                          headers={"Authorization": f"Basic {basic_credentials(creds.client_id, creds.client_secret)}"},
                          data={"grant_type": "client_credentials"})
        if r.status_code == 401:
            raise RunInvalid(f"digiRunner 拒絕 client {creds.client_id} 的帳密（401），請檢查 .env 的帳號密碼")
        if r.status_code >= 400:
            raise RunInvalid(f"向 digiRunner 申請 token 失敗：HTTP {r.status_code}")
        try:
            body = r.json()
        except ValueError:  # 例如 digiRunner 回了 HTML 錯誤頁
            raise RunInvalid(f"digiRunner 的 token 回應不是 JSON（HTTP {r.status_code}）") from None
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise RunInvalid("digiRunner 的 token 回應裡沒有 access_token")
        self._token = token

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
            return {"run_id": client.run_id, "days": days, "reflections": reflections,
                    "recovered": client.recovered, "token_requests": client.token_requests}
        else:
            raise RunInvalid(f"不認得的狀態 {status!r}")
        status = result["status"]
