"""Model access over the OpenAI chat-completions protocol.

Every supported backend — OpenAI, Groq, Gemini's compatibility endpoint,
OpenRouter, a local Ollama — speaks this one protocol, so there is a single
adapter here and no provider-specific branching anywhere in the codebase.
Switching providers is an environment-variable change.

Three behaviours are deliberate:

* **One round-trip when possible.** ``n=K`` asks for the whole ensemble in a
  single call. Some backends (Groq among them) reject ``n > 1``; the first
  rejection is cached per endpoint and later requests fan out concurrently
  instead. Either way the caller sees one ``complete()``.
* **A provider outage is an error, never an answer.** If both endpoints fail
  the caller gets ``provider_failure``. Degrading to "every note is no_op"
  would be a silently wrong schedule, which scores worse than a controlled 500
  and would not satisfy the mandatory-LLM requirement.
* **Nothing from a provider reaches a log or a response body.** Error text is
  redacted and clamped before it leaves this module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from openai import AsyncOpenAI

from app.config import Settings
from app.contracts import ErrorCategory, GridWiseError
from app.interpretation.prompts import RenderedPrompt, strict_schema
from app.observability import get_logger, redact

logger = get_logger(__name__)

_MAX_CONCURRENT_FANOUT = 8


@dataclass
class Endpoint:
    base_url: str
    api_key: str
    model: str
    label: str


@dataclass
class ProviderResult:
    texts: list[str]
    model: str
    calls: int


def _response_format(strict: bool) -> dict:
    if strict:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "directive_interpretation",
                "strict": True,
                "schema": strict_schema(),
            },
        }
    return {"type": "json_object"}


class LLMProvider:
    """Primary endpoint with an optional fallback, both reused across requests."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, AsyncOpenAI] = {}
        # Capability flags learned at runtime and cached per endpoint label.
        self._supports_n: dict[str, bool] = {}
        self._supports_schema: dict[str, bool] = {}

        self.endpoints: list[Endpoint] = []
        if settings.has_primary:
            self.endpoints.append(
                Endpoint(settings.llm_base_url, settings.llm_api_key, settings.llm_model, "primary")
            )
        if settings.has_fallback:
            self.endpoints.append(
                Endpoint(
                    settings.llm_fallback_base_url,
                    settings.llm_fallback_api_key or "not-needed",
                    settings.llm_fallback_model,
                    "fallback",
                )
            )
        if not self.endpoints:
            raise GridWiseError(
                ErrorCategory.provider_failure, "no language model endpoint configured"
            )

    def _client(self, endpoint: Endpoint) -> AsyncOpenAI:
        if endpoint.label not in self._clients:
            self._clients[endpoint.label] = AsyncOpenAI(
                base_url=endpoint.base_url,
                api_key=endpoint.api_key,
                timeout=self._settings.llm_timeout_seconds,
                max_retries=0,  # retries are budgeted by the caller, not the SDK
            )
        return self._clients[endpoint.label]

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    async def _one_call(self, endpoint: Endpoint, prompt: RenderedPrompt, n: int) -> list[str]:
        strict = self._supports_schema.get(endpoint.label, True)
        kwargs = {
            "model": endpoint.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": self._settings.llm_temperature,
            "response_format": _response_format(strict),
        }
        if n > 1:
            kwargs["n"] = n

        try:
            response = await self._client(endpoint).chat.completions.create(**kwargs)
        except Exception as exc:
            message = str(exc)
            # Learn and retry once when the endpoint rejects a capability rather
            # than the request itself.
            if strict and ("json_schema" in message or "response_format" in message):
                self._supports_schema[endpoint.label] = False
                logger.info(
                    "endpoint=%s rejected json_schema, using json_object: %s",
                    endpoint.label,
                    redact(message),
                )
                return await self._one_call(endpoint, prompt, n)
            raise

        return [choice.message.content or "" for choice in response.choices]

    async def _sample_endpoint(self, endpoint: Endpoint, prompt: RenderedPrompt, n: int) -> ProviderResult:
        if n == 1:
            return ProviderResult(await self._one_call(endpoint, prompt, 1), endpoint.model, 1)

        if self._supports_n.get(endpoint.label, True):
            try:
                texts = await self._one_call(endpoint, prompt, n)
                if len(texts) >= n:
                    self._supports_n[endpoint.label] = True
                    return ProviderResult(texts, endpoint.model, 1)
                # Honoured the call but ignored n: treat as unsupported.
                self._supports_n[endpoint.label] = False
            except Exception as exc:
                if "n" not in str(exc).lower():
                    raise
                self._supports_n[endpoint.label] = False
                logger.info("endpoint=%s n>1 unsupported, fanning out", endpoint.label)

        semaphore = asyncio.Semaphore(min(n, _MAX_CONCURRENT_FANOUT))

        async def one() -> list[str]:
            async with semaphore:
                return await self._one_call(endpoint, prompt, 1)

        batches = await asyncio.gather(*(one() for _ in range(n)), return_exceptions=True)
        texts = [t for batch in batches if isinstance(batch, list) for t in batch]
        if not texts:
            first = next((b for b in batches if isinstance(b, BaseException)), None)
            raise first if first else RuntimeError("no samples returned")
        return ProviderResult(texts, endpoint.model, n)

    async def complete(self, prompt: RenderedPrompt, n: int) -> ProviderResult:
        """Return up to ``n`` raw completions, trying each endpoint in order."""
        errors: list[str] = []
        for endpoint in self.endpoints:
            try:
                result = await asyncio.wait_for(
                    self._sample_endpoint(endpoint, prompt, n),
                    timeout=self._settings.llm_timeout_seconds * 2,
                )
                if result.texts:
                    return result
                errors.append(f"{endpoint.label}: empty response")
            except asyncio.TimeoutError:
                errors.append(f"{endpoint.label}: timeout")
                logger.warning("endpoint=%s timed out", endpoint.label)
            except Exception as exc:
                errors.append(f"{endpoint.label}: {redact(exc)}")
                logger.warning("endpoint=%s failed: %s", endpoint.label, redact(exc))

        # Diagnostics stay in the log (already redacted); the client gets a
        # fixed string. Provider error bodies have been observed to echo partial
        # key material, so none of it is forwarded to a response.
        logger.error("all endpoints failed: %s", "; ".join(errors))
        raise GridWiseError(
            ErrorCategory.provider_failure, "language model temporarily unavailable"
        )
