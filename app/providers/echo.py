"""A stand-in so the wiring can be tested before any model is reachable."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from .base import Event, api_messages


class EchoProvider:
    name = "echo"

    async def generate(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> str:
        last = api_messages(prompt, messages)[-1]["content"]
        return (
            "[echo - no model is connected]\n\n"
            f"You asked: {last[:400]}\n\n"
            "Set UBERMENSCH_PROVIDER in the server's .env to anthropic, claude-code, openai or ollama."
        )

    async def stream(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> AsyncIterator[Event]:
        text = await self.generate(prompt, system=system, messages=messages, deep=deep)
        yield {"type": "thinking"}
        for word in text.split(" "):
            await asyncio.sleep(0.03)
            yield {"type": "text", "delta": word + " "}
