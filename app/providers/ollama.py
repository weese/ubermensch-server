"""
A local model through Ollama's chat API. Streams NDJSON: one
{"message": {"content": ...}, "done": false} per piece, then {"done": true}.
Ollama usually runs on the host, not in this container, which is why the
default base URL is host.docker.internal.
"""
from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from ..config import Config
from .base import Event, ProviderError, api_messages, collect, joined_system


class OllamaProvider:
    name = "ollama"

    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base = cfg.ollama_base_url
        self._model = cfg.model
        self._max_tokens = cfg.max_tokens
        self._timeout = cfg.timeout
        self._transport = transport

    async def generate(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> str:
        return await collect(self.stream(prompt, system=system, messages=messages, deep=deep))

    async def stream(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> AsyncIterator[Event]:
        convo = api_messages(prompt, messages)
        body = {
            "model": self._model,
            "messages": [{"role": "system", "content": joined_system(system) or prompt}, *convo] if (system or messages) else convo,
            "stream": True,
            # Ollama's "think" switch errors on models that cannot think, so it
            # is left to the model's own default; `deep` has no effect here.
            "options": {"num_predict": self._max_tokens},
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10), transport=self._transport) as client:
                async with client.stream("POST", f"{self._base}/api/chat", json=body) as res:
                    if res.status_code != 200:
                        detail = (await res.aread()).decode(errors="replace")
                        raise ProviderError(_explain(res.status_code, detail, self._model, self._base))
                    yield {"type": "thinking"}
                    async for line in res.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            ev = json.loads(line)
                        except ValueError:
                            continue
                        if ev.get("error"):
                            raise ProviderError(f"Ollama: {ev['error']}")
                        delta = (ev.get("message") or {}).get("content")
                        if delta:
                            yield {"type": "text", "delta": delta}
                        if ev.get("done"):
                            break
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Could not reach Ollama at {self._base} ({exc.__class__.__name__}). "
                "Is it running, and reachable from the container?"
            ) from exc


def _explain(status: int, detail: str, model: str, base: str) -> str:
    try:
        msg = json.loads(detail).get("error") or detail
    except (ValueError, AttributeError):
        msg = detail
    msg = str(msg).strip()[:300]
    if status == 404 and "not found" in msg:
        return f"Ollama has no model {model!r}: {msg}. Pull it with `ollama pull {model}`."
    return f"Ollama error {status}: {msg}"
