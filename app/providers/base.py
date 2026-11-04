"""What every provider implements, and the small helpers they share."""
from __future__ import annotations

from typing import AsyncIterator, Protocol


class ProviderError(RuntimeError):
    """A failure the app should show as a sentence, not a stack trace."""


Event = dict
"""
One event of a streamed answer, as /v1/chat/stream writes it:
  {"type": "thinking"}                   the model started reasoning (optional)
  {"type": "text", "delta": "..."}       a piece of the answer
"""


class Provider(Protocol):
    name: str

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        deep: bool = False,
    ) -> str:
        """The whole reply. `prompt` is the flattened fallback when `messages` is absent."""
        ...

    def stream(
        self,
        prompt: str,
        *,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        deep: bool = False,
    ) -> AsyncIterator[Event]:
        """The same reply as it is written. Raises ProviderError."""
        ...


SYSTEM_SPLIT = "<!-- ubermensch:per-turn -->"
"""
The app puts this line between the part of its system prompt that never
changes (instructions, tool guides, the app guide) and the part that does
(the person's context this turn). Everything before it is the same on every
request, so providers cache it; an older server just passes the line along.
"""


def split_system(system: str | None) -> tuple[str | None, str]:
    """(static, per_turn). Without the marker the whole prompt counts as static."""
    if not system or SYSTEM_SPLIT not in system:
        return system, ""
    static, _, per_turn = system.partition(SYSTEM_SPLIT)
    return static.strip(), per_turn.strip()


def joined_system(system: str | None) -> str | None:
    """The prompt with the marker removed, for providers that take one string (their prefix caching still helps)."""
    static, per_turn = split_system(system)
    return "\n\n".join(p for p in (static, per_turn) if p) or None


def api_messages(prompt: str, messages: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """
    The conversation as role/content pairs. Prefers the structured form the
    app sends; falls back to the flat prompt as one user turn so an old
    client still gets an answer. The last turn must be the user's.
    """
    out = [
        {"role": m["role"], "content": m["content"]}
        for m in (messages or [])
        if m.get("role") in ("user", "assistant") and m.get("content")
    ] or [{"role": "user", "content": prompt}]
    if out[-1]["role"] != "user":
        raise ProviderError("The conversation must end with the user's turn.")
    return out


async def collect(stream: AsyncIterator[Event]) -> str:
    """generate() in terms of stream(): every provider writes the stream once."""
    text = ""
    async for ev in stream:
        if ev.get("type") == "text":
            text += ev.get("delta", "")
    text = text.strip()
    if not text:
        raise ProviderError("The model returned no text.")
    return text
