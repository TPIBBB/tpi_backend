import json
from types import SimpleNamespace

import pytest

from civsim.agents.llm_client import (
    DEFAULT_GEMINI_MODEL,
    GeminiClient,
    LLMError,
    load_dotenv,
    make_client,
)


class FakeModels:
    """模擬 google-genai 的 client.models，不連網。"""

    def __init__(self, text='{"actions": []}', candidates=None):
        self.text = text
        self.candidates = candidates
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        usage = SimpleNamespace(prompt_token_count=10, candidates_token_count=5,
                                thoughts_token_count=None, total_token_count=15)
        return SimpleNamespace(text=self.text, usage_metadata=usage,
                               candidates=self.candidates, prompt_feedback=None)


def make_gemini(**kwargs):
    models = FakeModels(**kwargs)
    return GeminiClient(model="gemini-test", seed=7, client=SimpleNamespace(models=models)), models


def test_gemini_sends_system_prompt_and_json_mode():
    client, models = make_gemini()
    assert client.complete("系統", "使用者") == '{"actions": []}'
    call = models.calls[0]
    assert call["model"] == "gemini-test" and call["contents"] == "使用者"
    assert call["config"] == {"system_instruction": "系統", "temperature": 0.0,
                              "response_mime_type": "application/json", "seed": 7}


def test_gemini_records_token_usage():
    client, _ = make_gemini()
    client.complete("系統", "使用者")
    assert client.last_usage == {"prompt_tokens": 10, "output_tokens": 5,
                                 "thinking_tokens": 0, "total_tokens": 15}


def test_gemini_empty_response_raises():
    client, _ = make_gemini(text=None, candidates=[SimpleNamespace(finish_reason="SAFETY")])
    with pytest.raises(LLMError, match="SAFETY"):
        client.complete("系統", "使用者")


def test_gemini_requires_api_key():
    pytest.importorskip("google.genai")
    with pytest.raises(ValueError, match="API key"):
        GeminiClient(api_key="")


def test_make_client_without_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert make_client() is None


def test_make_client_gemini_reads_env(monkeypatch):
    pytest.importorskip("google.genai")
    monkeypatch.setenv("LLM_PROVIDER", "Gemini")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_SEED", "3")
    client = make_client()
    assert isinstance(client, GeminiClient)
    assert client.model == DEFAULT_GEMINI_MODEL and client.seed == 3 and client.temperature == 0


def test_make_client_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="unknown"):
        make_client()


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# 註解\nCIVSIM_A="from-file"\nCIVSIM_B=from-file\n\nnot-a-pair\n', encoding="utf-8")
    monkeypatch.delenv("CIVSIM_A", raising=False)
    monkeypatch.setenv("CIVSIM_B", "already-set")
    load_dotenv(env)
    import os

    assert os.environ["CIVSIM_A"] == "from-file" and os.environ["CIVSIM_B"] == "already-set"
    monkeypatch.delenv("CIVSIM_A")


# ---- OpenAI 相容（Modal 上的 vLLM、Ollama）----
def make_openai(responses):
    httpx = pytest.importorskip("httpx")
    from civsim.agents.llm_client import OpenAICompatibleClient

    sent = []

    def handler(request):
        sent.append(request)
        status, body = responses.pop(0)
        return httpx.Response(status, json=body)

    client = OpenAICompatibleClient(model="qwen", base_url="https://x.modal.run/v1/", api_key="k", seed=7,
                                    transport=httpx.MockTransport(handler))
    client._sleep = lambda s: None  # 測試不要真的等
    return client, sent


OK = (200, {"choices": [{"message": {"content": '{"actions": []}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def test_openai_compatible_sends_chat_request():
    client, sent = make_openai([OK])
    assert client.complete("系統", "使用者") == '{"actions": []}'
    req = sent[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://x.modal.run/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer k"
    assert body["messages"] == [{"role": "system", "content": "系統"}, {"role": "user", "content": "使用者"}]
    assert body["response_format"] == {"type": "json_object"} and body["seed"] == 7 and body["temperature"] == 0
    assert client.last_usage == {"prompt_tokens": 10, "output_tokens": 5, "thinking_tokens": 0, "total_tokens": 15}


def test_openai_compatible_retries_then_gives_up():
    client, sent = make_openai([(503, {}), OK])
    assert client.complete("s", "u") == '{"actions": []}' and len(sent) == 2
    client, _ = make_openai([(429, {})] * 4)
    with pytest.raises(LLMError, match="重試 4 次"):
        client.complete("s", "u")


def test_openai_compatible_does_not_retry_client_errors():
    client, sent = make_openai([(401, {"error": "bad key"}), OK])
    with pytest.raises(LLMError, match="401"):
        client.complete("s", "u")
    assert len(sent) == 1


def test_make_client_modal_and_ollama(monkeypatch):
    pytest.importorskip("httpx")
    from civsim.agents.llm_client import OpenAICompatibleClient

    monkeypatch.setenv("LLM_PROVIDER", "modal")
    monkeypatch.setenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    monkeypatch.setenv("LLM_BASE_URL", "https://x.modal.run/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    client = make_client()
    assert isinstance(client, OpenAICompatibleClient) and client.base_url == "https://x.modal.run/v1"
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_BASE_URL")
    assert make_client().base_url == "http://localhost:11434/v1"
    monkeypatch.delenv("LLM_MODEL")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        make_client()


def test_openai_compatible_follows_modal_redirect():
    httpx = pytest.importorskip("httpx")
    from civsim.agents.llm_client import OpenAICompatibleClient

    def handler(request):
        if "__modal_attempt_token" not in str(request.url):  # Modal 冷啟動超過 150 秒：先回 303
            return httpx.Response(303, headers={"location": str(request.url) + "?__modal_attempt_token=t"})
        return httpx.Response(*OK[:1], json=OK[1])

    client = OpenAICompatibleClient(model="qwen", base_url="https://x.modal.run/v1",
                                    transport=httpx.MockTransport(handler))
    assert client.complete("s", "u") == '{"actions": []}'


def test_openai_compatible_non_json_response_is_llm_error():
    httpx = pytest.importorskip("httpx")
    from civsim.agents.llm_client import OpenAICompatibleClient

    client = OpenAICompatibleClient(model="qwen", base_url="https://x/v1",
                                    transport=httpx.MockTransport(lambda r: httpx.Response(200, text="")))
    with pytest.raises(LLMError, match="不是 JSON"):
        client.complete("s", "u")
