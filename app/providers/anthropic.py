"""
Claude via the Messages API. Opus 5.5 by default: adaptive thinking is the
model's default, depth is set with `effort`, and `fallbacks="default"` lets a
policy decline be re-run on a substitute model server-side rather than
surfacing as an empty answer. Streaming even for one-shot replies, so a long
answer never hits an HTTP timeout.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from ..config import Config
from .base import Event, ProviderError, api_messages, collect, split_system

log = logging.getLogger("ubermensch.anthropic")

# `deep` asks for one step more than the configured effort.
_DEEPER = {"low": "medium", "medium": "high", "high": "max", "max": "max"}


def _system_blocks(system: str) -> list[dict]:
    """
    The static part as its own block with a cache breakpoint, the per-turn
    part after it: every question re-reads the instructions and the app guide
    from the cache instead of paying for them again.
    """
    static, per_turn = split_system(system)
    blocks: list[dict] = [{"type": "text", "text": static or "", "cache_control": {"type": "ephemeral"}}]
    if per_turn:
        blocks.append({"type": "text", "text": per_turn})
    return blocks


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg: Config) -> None:
        import anthropic  # imported here so other providers need no SDK

        if not cfg.anthropic_key:
            raise SystemExit("UBERMENSCH_PROVIDER=anthropic needs ANTHROPIC_API_KEY in the environment.")
        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic(api_key=cfg.anthropic_key)
        self._model = cfg.model
        self._effort = cfg.effort
        self._max_tokens = cfg.max_tokens

    async def generate(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> str:
        return await collect(self.stream(prompt, system=system, messages=messages, deep=deep))

    async def stream(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> AsyncIterator[Event]:
        a = self._anthropic
        effort = _DEEPER[self._effort] if deep else self._effort
        kwargs = dict(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_system_blocks(system or prompt),
            messages=api_messages(prompt, messages),
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        try:
            async with self._client.beta.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "content_block_start" and getattr(event.content_block, "type", "") == "thinking":
                        yield {"type": "thinking"}
                    elif event.type == "text":
                        yield {"type": "text", "delta": event.text}
                msg = await stream.get_final_message()
        except a.NotFoundError as exc:
            raise ProviderError(f"Model {self._model!r} not available: {exc.message}") from exc
        except a.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit reached - try again in a moment.") from exc
        except a.AuthenticationError as exc:
            raise ProviderError("Anthropic rejected the API key on the server.") from exc
        except a.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except a.APIConnectionError as exc:
            raise ProviderError("Could not reach the Anthropic API from the server.") from exc

        if msg.stop_reason == "refusal":
            why = getattr(getattr(msg, "stop_details", None), "category", None)
            raise ProviderError(f"The model declined this request ({why or 'policy'}).")
        if msg.stop_reason == "max_tokens":
            log.warning("reply truncated at max_tokens=%d", self._max_tokens)
