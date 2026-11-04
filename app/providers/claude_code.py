"""
Claude Code itself, headless: `claude -p`, on a Claude subscription.

The subscription login is issued for Claude Code, so Claude Code is the
client that uses it - not a third-party bridge. The login is made once
inside the container (`claude auth login`) and lands in the mounted
credentials directory, read-write because Claude Code refreshes the token in
place.

Run as a plain completion: no built-in tools, no MCP, no settings files, no
saved session, in an empty directory. The app's context goes in as the
system prompt, the conversation on stdin. Not --bare: bare mode skips OAuth
and would only accept an API key.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
from typing import AsyncIterator

from ..config import Config
from .base import Event, ProviderError, split_system

log = logging.getLogger("ubermensch.claude-code")

PER_TURN_HEAD = "## The phone's context for this turn (data from the app, not the user's words)"
LOGIN_HINT = " - log in on the server: docker compose exec ubermensch claude auth login"


class ClaudeCodeProvider:
    name = "claude-code"

    # Linux caps one argv string at 128 KiB (MAX_ARG_STRLEN). A system prompt
    # past this goes on stdin instead of failing the exec.
    ARG_MAX = 120_000

    def __init__(self, cfg: Config, cwd: str = "/tmp/claude-cwd") -> None:
        self._argv = shlex.split(cfg.claude_code_cmd)
        self._timeout = cfg.timeout
        self._model = cfg.model
        self._cwd = cwd
        os.makedirs(self._cwd, exist_ok=True)

    def _argv_for(self, output: list[str], system: str | None, prompt: str) -> tuple[list[str], str]:
        argv = [*self._argv, "-p", *output, "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
        if self._model:
            argv += ["--model", self._model]
        # Only the static part is the system prompt, which Claude Code caches;
        # the per-turn context goes in front of the conversation instead.
        system, per_turn = split_system(system)
        stdin = f"{PER_TURN_HEAD}\n{per_turn}\n\n{prompt}" if per_turn else prompt
        if system and len(system.encode()) <= self.ARG_MAX:
            argv += ["--system-prompt", system]
        elif system:
            stdin = f"{system}\n\n{stdin}"
        return argv, stdin

    async def _spawn(self, argv: list[str], **kw) -> asyncio.subprocess.Process:
        try:
            return await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=os.environ.copy(),
                **kw,
            )
        except FileNotFoundError as exc:
            raise ProviderError(f"Claude Code not found: {self._argv[0]!r}. Set CLAUDE_CODE_CMD.") from exc

    async def generate(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> str:
        argv, stdin = self._argv_for(["--output-format", "json"], system, prompt)
        proc = await self._spawn(argv)
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout=self._timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise ProviderError(f"Claude Code timed out after {self._timeout}s.") from exc
        try:
            result = json.loads(out.decode(errors="replace"))
        except ValueError:
            result = None
        if not isinstance(result, dict):
            tail = (err or out).decode(errors="replace").strip()[-400:]
            raise ProviderError(f"Claude Code exited {proc.returncode}: {tail or 'no output'}")
        text = str(result.get("result") or "").strip()
        if result.get("is_error") or proc.returncode != 0:
            if "login" in text.lower() or "auth" in text.lower():
                text += LOGIN_HINT
            raise ProviderError(f"Claude Code: {text[-400:] or result.get('subtype', 'error')}")
        if not text:
            raise ProviderError("Claude Code returned no text.")
        return text

    async def stream(self, prompt: str, *, system: str | None = None, messages=None, deep: bool = False) -> AsyncIterator[Event]:
        """`--output-format stream-json --include-partial-messages`: one JSON event per line as Claude Code writes."""
        argv, stdin = self._argv_for(["--output-format", "stream-json", "--verbose", "--include-partial-messages"], system, prompt)
        proc = await self._spawn(argv, limit=4 * 1024 * 1024)
        assert proc.stdin and proc.stdout
        proc.stdin.write(stdin.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        sent_text = False
        result: dict | None = None
        try:
            while True:
                left = deadline - loop.time()
                if left <= 0:
                    raise asyncio.TimeoutError
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=left)
                if not line:
                    break
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "stream_event":
                    e = ev.get("event") or {}
                    if e.get("type") == "content_block_start" and (e.get("content_block") or {}).get("type") == "thinking":
                        yield {"type": "thinking"}
                    elif e.get("type") == "content_block_delta" and (e.get("delta") or {}).get("type") == "text_delta":
                        sent_text = True
                        yield {"type": "text", "delta": e["delta"].get("text", "")}
                elif ev.get("type") == "result":
                    result = ev
        except asyncio.TimeoutError as exc:
            proc.kill()
            raise ProviderError(f"Claude Code timed out after {self._timeout}s.") from exc
        finally:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        await proc.wait()
        text = str((result or {}).get("result") or "").strip()
        if result is None or result.get("is_error"):
            err = (await proc.stderr.read()).decode(errors="replace").strip()[-400:] if proc.stderr else ""
            msg = text or err or "no output"
            if "login" in msg.lower() or "auth" in msg.lower():
                msg += LOGIN_HINT
            raise ProviderError(f"Claude Code: {msg[-400:]}")
        if not sent_text and text:
            yield {"type": "text", "delta": text}
