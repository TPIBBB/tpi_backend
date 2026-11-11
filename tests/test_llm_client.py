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
