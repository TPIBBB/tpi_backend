"""LLM 供應商與共用工具。負責人：Agent。

所有 LLM 呼叫都經過有 complete(system, user) -> str 的 LLMClient：
- GeminiClient：呼叫 Google Gemini API（免費版每天只有少量呼叫次數），或 GCP 上的 Vertex AI（付費、沒有每日上限）
- OpenAICompatibleClient：呼叫 OpenAI 相容 API，例如 Modal 上自己架的 vLLM（modal/llm_server.py）或本機 Ollama
- ScriptedClient：不連網的假 LLM，給測試與流程演練用

環境變數（可寫在專案根目錄的 .env，由 cli 讀入）：
- LLM_PROVIDER：gemini | vertex | modal（= openai_compatible）| ollama；留空表示不使用 LLM
- LLM_MODEL：模型 ID；gemini、vertex 預設 DEFAULT_GEMINI_MODEL，其他要填伺服器上的模型名稱。正式實驗前要鎖定
- GOOGLE_CLOUD_PROJECT：vertex 用的 GCP 專案 ID；登入方式是先執行 gcloud auth application-default login
- GOOGLE_CLOUD_LOCATION：vertex 的區域，預設 global
- LLM_BASE_URL：OpenAI 相容 API 的網址（到 /v1 為止）；ollama 預設 http://localhost:11434/v1
- LLM_API_KEY（或 GEMINI_API_KEY）：Gemini API key，或 Modal 伺服器的金鑰
- LLM_TEMPERATURE：預設 0，讓結果盡量可重現
- LLM_SEED：固定的亂數種子（選填），Gemini 會盡量對相同輸入給出相同回應
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"  # Gemini 文件標示為 Stable 的 Flash 模型
RETRY_STATUS_CODES = (408, 429, 500, 502, 503, 504)  # 逾時、額度、伺服器錯誤才重試
MAX_REDIRECTS = 6  # Modal 每 150 秒轉址一次：最多等約 15 分鐘


class ParseError(ValueError):
    """LLM 回應無法解析成需要的格式。"""


class LLMError(RuntimeError):
    """LLM 有回應，但沒有可用的文字（例如被安全過濾或輸出被截斷）。"""


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


@dataclass
class LLMCall:
    """一次 LLM 呼叫的紀錄，用來重現與分析實驗。"""

    tick: int
    agent_id: str
    prompt_version: str
    model: str
    used_llm: bool
    trigger: str  # 為什麼呼叫（或不呼叫）LLM
    prompt: str | None = None
    response: str | None = None
    error: str | None = None
    skipped: list[str] = field(default_factory=list)
    used_fallback: bool = False
    usage: dict[str, int] | None = None  # token 用量，用來估算費用


# ---- 解析 ----
def extract_json(text: str) -> Any:
    """容忍常見的格式偏差：```json 區塊、JSON 前後夾雜說明文字。"""
    text = (text or "").strip()
    try:
        return json.loads(text)  # 先試整段，內容裡的 ``` 才不會被誤認成外層的程式碼區塊
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ParseError("回應中找不到 JSON 物件") from None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise ParseError(f"JSON 格式錯誤：{e}") from None


# ---- 供應商 ----
@dataclass
class ScriptedClient:
    """不連網的假 LLM：用固定回應或函式產生回應。給測試與流程演練用。"""

    respond: Callable[[str, str], str] | list[str]
    model: str = "scripted"
    last_usage: dict[str, int] | None = None

    def complete(self, system: str, user: str) -> str:
        if callable(self.respond):
            return self.respond(system, user)
        if not self.respond:
            raise RuntimeError("ScriptedClient 的回應已用完")
        return self.respond.pop(0)


class GeminiClient:
    """呼叫 Google Gemini API（google-genai SDK）。

    逾時、額度不足與伺服器錯誤由 SDK 自動重試；重試後仍失敗會丟出例外，
    由呼叫端（例如 LLMGovernment）記錄並改用 fallback。
    """

    def __init__(
        self,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key: str | None = None,
        vertex: bool = False,  # True：走 GCP 的 Vertex AI，用 project + gcloud 登入，或 Vertex 的 API key
        project: str | None = None,
        location: str | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout_s: float = 60.0,
        attempts: int = 4,
        json_mode: bool = True,
        client: Any = None,  # 測試時可傳入假的 SDK client
    ):
        self.model = model
        self.provider = "vertex" if vertex else "gemini"
        self.temperature = temperature
        self.seed = seed
        self.json_mode = json_mode
        self.last_usage: dict[str, int] | None = None
        if client is None:
            client = self._make_sdk_client(api_key, vertex, project, location, timeout_s, attempts)
        self._client = client

    @staticmethod
    def _make_sdk_client(
        api_key: str | None, vertex: bool, project: str | None, location: str | None,
        timeout_s: float, attempts: int,
    ) -> Any:
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise ImportError('尚未安裝 Gemini SDK，請執行 pip install -e ".[llm]"') from e
        if vertex and project:
            # 用 gcloud auth application-default login 的登入資訊，費用算在這個 GCP 專案
            auth: dict[str, Any] = {"vertexai": True, "project": project, "location": location or "global"}
        elif vertex and api_key:
            auth = {"vertexai": True, "api_key": api_key}  # Vertex AI 的 API key（express mode）
        elif vertex:
            raise ValueError("Vertex AI 要設定 GOOGLE_CLOUD_PROJECT（GCP 專案 ID），或 Vertex 的 API key（LLM_API_KEY）")
        elif api_key:
            auth = {"api_key": api_key}
        else:
            raise ValueError("尚未設定 Gemini API key（LLM_API_KEY 或 GEMINI_API_KEY）")
        return genai.Client(
            **auth,
            http_options=types.HttpOptions(
                timeout=int(timeout_s * 1000),  # SDK 的單位是毫秒
                retry_options=types.HttpRetryOptions(
                    attempts=attempts, http_status_codes=list(RETRY_STATUS_CODES)
                ),
            ),
        )

    def complete(self, system: str, user: str) -> str:
        config: dict[str, Any] = {"system_instruction": system, "temperature": self.temperature}
        if self.json_mode:
            config["response_mime_type"] = "application/json"  # 要求模型只回傳 JSON
        if self.seed is not None:
            config["seed"] = self.seed

        response = self._client.models.generate_content(model=self.model, contents=user, config=config)
        self.last_usage = _usage(response)
        text = response.text
        if not text:
            raise LLMError(f"Gemini 沒有回傳文字（finish_reason={_finish_reason(response)}）")
        return text


class OpenAICompatibleClient:
    """呼叫 OpenAI 相容的 Chat Completions API：Modal 上的 vLLM（modal/llm_server.py）、Ollama 等。

    base_url 指到 /v1 為止，例如 https://xxx.modal.run/v1 或 http://localhost:11434/v1。
    遇到逾時、限流與伺服器錯誤會等一下再重試；重試後仍失敗會丟出 LLMError，由 LLMGovernment 改用 fallback。
    """

    provider = "openai_compatible"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        temperature: float = 0.0,
        seed: int | None = None,
        timeout_s: float = 300.0,  # 單次連線最多等多久；Modal 每 150 秒會轉址一次
        attempts: int = 4,
        json_mode: bool = True,
        transport: Any = None,  # 測試時可傳入 httpx.MockTransport
    ):
        try:
            import httpx
        except ImportError as e:
            raise ImportError('尚未安裝 httpx，請執行 pip install -e ".[llm]"') from e
        if not model:
            raise ValueError("OpenAI 相容模式要設定 LLM_MODEL（伺服器上的模型名稱）")
        if not base_url:
            raise ValueError("OpenAI 相容模式要設定 LLM_BASE_URL，例如 https://xxx.modal.run/v1")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.seed = seed
        self.attempts = attempts
        self.json_mode = json_mode
        self.last_usage: dict[str, int] | None = None
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # Modal 的請求超過 150 秒（例如冷啟動）會回 303，要照 Location 去拿結果，所以要跟著轉址。
        # 每次轉址約 150 秒，最多 6 次，也就是一次請求最多等約 15 分鐘，伺服器起不來時不會一直卡住
        self._http = httpx.Client(headers=headers, timeout=timeout_s, transport=transport,
                                  follow_redirects=True, max_redirects=MAX_REDIRECTS)
        self._sleep = time.sleep

    def complete(self, system: str, user: str) -> str:
        import httpx

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}  # 要求模型只回傳 JSON
        if self.seed is not None:
            body["seed"] = self.seed

        error = ""
        for attempt in range(self.attempts):
            if attempt:
                self._sleep(min(2 ** attempt, 30))
            try:
                r = self._http.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.TooManyRedirects:
                raise LLMError(f"等了約 {MAX_REDIRECTS * 150 // 60} 分鐘伺服器還沒準備好，"
                               "請看 Modal 的 Logs 確認模型有沒有啟動成功") from None
            except httpx.TransportError as e:  # 連不上、逾時
                error = f"{type(e).__name__}: {e}"
                continue
            if r.status_code in RETRY_STATUS_CODES:
                error = f"HTTP {r.status_code}: {r.text[:300]}"
                continue
            if r.status_code >= 300:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            try:
                data = r.json()
            except ValueError:
                raise LLMError(f"回應不是 JSON（HTTP {r.status_code}）：{r.text[:300]!r}") from None
            usage = data.get("usage") or {}
            self.last_usage = {
                "prompt_tokens": usage.get("prompt_tokens") or 0,
                "output_tokens": usage.get("completion_tokens") or 0,
                "thinking_tokens": 0,
                "total_tokens": usage.get("total_tokens") or 0,
            } if usage else None
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content")
            if not text:
                raise LLMError(f"模型沒有回傳文字（finish_reason={choice.get('finish_reason')}）")
            return text
        raise LLMError(f"重試 {self.attempts} 次仍失敗：{error}")


def _usage(response: Any) -> dict[str, int] | None:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    fields_ = {
        "prompt_tokens": "prompt_token_count",
        "output_tokens": "candidates_token_count",
        "thinking_tokens": "thoughts_token_count",
        "total_tokens": "total_token_count",
    }
    return {k: getattr(meta, v) or 0 for k, v in fields_.items()}


def _finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None)
        return f"沒有候選回應，prompt_feedback={feedback}"
    return str(getattr(candidates[0], "finish_reason", "未知"))


def make_client() -> LLMClient | None:
    """依環境變數建立 LLM client；LLM_PROVIDER 留空時回傳 None。"""
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        return None
    if provider in ("gemini", "vertex"):
        seed = os.getenv("LLM_SEED", "").strip()
        vertex = provider == "vertex"
        return GeminiClient(
            model=os.getenv("LLM_MODEL", "").strip() or DEFAULT_GEMINI_MODEL,
            api_key=os.getenv("LLM_API_KEY", "").strip()
            or ("" if vertex else os.getenv("GEMINI_API_KEY", "").strip()),
            vertex=vertex,
            project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() if vertex else None,
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "").strip() if vertex else None,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0") or 0),
            seed=int(seed) if seed else None,
        )
    if provider in ("openai_compatible", "modal", "ollama"):
        seed = os.getenv("LLM_SEED", "").strip()
        return OpenAICompatibleClient(
            model=os.getenv("LLM_MODEL", "").strip(),
            base_url=os.getenv("LLM_BASE_URL", "").strip()
            or ("http://localhost:11434/v1" if provider == "ollama" else ""),
            api_key=os.getenv("LLM_API_KEY", "").strip() or None,
            temperature=float(os.getenv("LLM_TEMPERATURE", "0") or 0),
            seed=int(seed) if seed else None,
        )
    raise ValueError(f"未知的 LLM_PROVIDER：{provider}（目前支援 gemini、vertex、openai_compatible／modal、ollama）")


def load_dotenv(path: str | Path = ".env") -> None:
    """讀入 .env 的 KEY=VALUE；已經設定的環境變數不會被覆蓋。不依賴額外套件。"""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
