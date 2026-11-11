"""Клиенты языковых моделей с общим интерфейсом LLMClient."""

import re

import config
from contracts import LLMClient

OLLAMA_TIMEOUT = 600


class GigaChatClient:
    """Клиент GigaChat API."""

    def __init__(self):
        self.model = config.GIGACHAT_MODEL
        self._client = None
        self._init_error = ""
        try:
            from gigachat import GigaChat

            self._client = GigaChat(
                credentials=config.GIGACHAT_CREDENTIALS,
                model=self.model,
                verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
            )
        except Exception as exc:
            self._init_error = str(exc)

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        if self._client is None:
            return f"GigaChat недоступен: {self._init_error}"
        try:
            response = self._client.chat({
                "messages": messages,
                "temperature": temperature,
            })
            content = response.choices[0].message.content
        except Exception as exc:
            return f"GigaChat недоступен: {exc}"
        if not content:
            return "GigaChat вернул пустой ответ"
        return content.strip()

    def count_tokens(self, text: str) -> int:
        return len(text) // 3


class OllamaClient:
    """Клиент локальной модели через HTTP API Ollama."""

    def __init__(self):
        self.model = config.OLLAMA_MODEL
        self.host = config.OLLAMA_HOST.rstrip("/")

    def generate(self, messages: list[dict], temperature: float = 0.3) -> str:
        import requests

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                },
                timeout=OLLAMA_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            return f"Ollama недоступна: {exc}"
        except ValueError as exc:
            return f"Ollama вернула некорректный ответ: {exc}"

        message = data.get("message") or {}
        content = message.get("content") or ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if not content:
            return "Ollama вернула пустой ответ"
        return content

    def count_tokens(self, text: str) -> int:
        return len(text) // 3


def build_client() -> LLMClient:
    """Выбрать бэкенд по LLM_BACKEND."""
    if config.LLM_BACKEND == "ollama":
        return OllamaClient()
    if config.LLM_BACKEND == "gigachat":
        return GigaChatClient()
    if config.LLM_BACKEND == "fake":
        from fake_llm import FakeClient

        return FakeClient()
    raise ValueError(
        f"Неизвестный LLM_BACKEND: {config.LLM_BACKEND!r}. "
        f"Допустимо: gigachat | ollama | fake"
    )
