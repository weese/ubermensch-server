"""
ChatGPT models via the OpenAI API, or any server that speaks the same
Chat Completions protocol (set OPENAI_BASE_URL: LM Studio, vLLM, OpenRouter,
Groq, ...). Plain HTTP with httpx, no SDK: the protocol is small and stable,
and one fewer dependency to pin.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ..config import Config
from .base import Event, ProviderError, api_messages, collect, joined_system

_DEEPER = {"low": "medium", "medium": "high", "high": "high", "max": "high"}


def _reasoning_model(model: str) -> bool:
    """Models that take reasoning_effort; others reject the parameter."""
    m = model.lower()
    return m.startswith(("o1", "o3", "o4", "gpt-5"))


class OpenAIProvider:
    name = "openai"

    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not cfg.openai_key and "api.openai.com" in cfg.openai_base_url:
            raise SystemExit("UBERMENSCH_PROVIDER=openai needs OPENAI_API_KEY in the environment.")
        self._base = cfg.openai_base_url
        self._key = cfg.openai_key
        self._model = cfg.model
        self._effort = cfg.effort
        self._max_tokens = cfg.max_tokens
        self._timeout = cfg.timeout
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(self._timeout, connect=10), transport=self._transport)

    def _body(self, prompt: str, system: str | None, messages, deep: bool) -> dict:
        convo = api_messages(prompt, messages)
        body: dict = {
            "model": self._model,
            "messages": [{"role": "system", "content": joined_system(system) or prompt}, *convo] if (system or messages) else convo,
            "stream": True,
            "max_completion_tokens": self._max_tokens,
        }
        if _reasoning_model(self._model):
            # OpenAI knows low/medium/high; Anthropic's "max" maps to high.
            base = "high" if self._effort == "max" else self._effort
            body["reasoning_effort"] = _DEEPER[base] if deep else base
        return body

    async def generate(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> str:
        return await collect(self.stream(prompt, system=system, messages=messages, deep=deep))

    async def stream(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> AsyncIterator[Event]:
        body = self._body(prompt, system, messages, deep)
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self._base}/chat/completions", json=body) as res:
                    if res.status_code != 200:
                        detail = (await res.aread()).decode(errors="replace")
                        raise ProviderError(_explain(res.status_code, detail, self._model))
                    yield {"type": "thinking"}
                    async for line in res.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            ev = json.loads(payload)
                        except ValueError:
                            continue
                        for choice in ev.get("choices") or []:
                            delta = (choice.get("delta") or {}).get("content")
                            if delta:
                                yield {"type": "text", "delta": delta}
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach the OpenAI-compatible API at {self._base}: {exc.__class__.__name__}.") from exc


def _explain(status: int, detail: str, model: str) -> str:
    try:
        msg = json.loads(detail).get("error", {}).get("message") or detail
    except (ValueError, AttributeError):
        msg = detail
    msg = str(msg).strip()[:300]
    if status == 401:
        return "The OpenAI-compatible API rejected the key on the server."
    if status == 404:
        return f"Model {model!r} not found at the OpenAI-compatible API: {msg}"
    if status == 429:
        return "OpenAI rate limit or quota reached - try again in a moment."
    return f"OpenAI-compatible API error {status}: {msg}"
