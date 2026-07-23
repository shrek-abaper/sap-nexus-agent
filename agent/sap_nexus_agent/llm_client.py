from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


class LlmUnavailable(RuntimeError):
    """Raised when the configured model gateway cannot provide a trusted response."""


@dataclass(frozen=True)
class LlmSettings:
    api_key: str | None = None
    base_url: str | None = None
    model: str = "DeepSeek-V3"
    max_retries: int = 3
    timeout_intent: float = 12.0
    missing: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url and not self.missing)

    def __repr__(self) -> str:
        redacted_key = "***" if self.api_key else None
        redacted_base_url = "***" if self.base_url else None
        return (
            "LlmSettings("
            f"api_key={redacted_key!r}, "
            f"base_url={redacted_base_url!r}, "
            f"model={self.model!r}, "
            f"max_retries={self.max_retries!r}, "
            f"timeout_intent={self.timeout_intent!r}, "
            f"missing={self.missing!r})"
        )


def load_llm_settings(*, load_dotenv_file: bool = True) -> LlmSettings:
    if load_dotenv_file:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:
            # dotenv is a convenience for local runs; env vars still work without it.
            pass

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL_NAME", "DeepSeek-V3")
    max_retries = _int_env("LLM_MAX_RETRIES", 3)
    timeout_intent = _float_env("LLM_TIMEOUT_INTENT", 12.0)
    missing = tuple(name for name, value in (("LLM_API_KEY", api_key), ("LLM_BASE_URL", base_url)) if not value)
    return LlmSettings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_retries=max_retries,
        timeout_intent=timeout_intent,
        missing=missing,
    )


class OpenAiCompatibleLlmClient:
    def __init__(self, settings: LlmSettings | None = None):
        self.settings = settings or load_llm_settings()
        if not self.settings.available:
            raise LlmUnavailable(f"LLM configuration unavailable: missing {', '.join(self.settings.missing)}")

        try:
            from openai import APIConnectionError, APIStatusError, OpenAI
        except Exception as exc:  # pragma: no cover - depends on optional runtime package state
            raise LlmUnavailable("OpenAI SDK is not available") from exc

        self._api_connection_error = APIConnectionError
        self._api_status_error = APIStatusError
        self._client = OpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
            max_retries=self.settings.max_retries,
        )

    def chat_json(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 400) -> dict[str, Any]:
        try:
            response = self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.settings.timeout_intent,
            )
            content = response.choices[0].message.content
            if not content:
                raise LlmUnavailable("LLM returned empty JSON content")
            import json

            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise LlmUnavailable("LLM JSON content is not an object")
            return payload
        except (self._api_connection_error, TimeoutError) as exc:
            raise LlmUnavailable("LLM connection failed") from exc
        except self._api_status_error as exc:
            raise LlmUnavailable(f"LLM API status error: {getattr(exc, 'status_code', 'unknown')}") from exc
        except Exception as exc:
            raise LlmUnavailable("LLM JSON call failed") from exc

    def chat_text(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = 400) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=self.settings.timeout_intent,
            )
            content = response.choices[0].message.content
        except (self._api_connection_error, TimeoutError) as exc:
            raise LlmUnavailable("LLM connection failed") from exc
        except self._api_status_error as exc:
            raise LlmUnavailable(f"LLM API status error: {getattr(exc, 'status_code', 'unknown')}") from exc
        except LlmUnavailable:
            raise
        except Exception as exc:
            raise LlmUnavailable("LLM text call failed") from exc
        if not content:
            raise LlmUnavailable("LLM returned empty text content")
        return content


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
