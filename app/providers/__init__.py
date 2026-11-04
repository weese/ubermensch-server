"""
The model behind the server, chosen with UBERMENSCH_PROVIDER.

  anthropic    Claude via the Messages API (ANTHROPIC_API_KEY).
  claude-code  Claude Code headless (`claude -p`) on a Claude subscription,
               logged in once inside the container.
  openai       ChatGPT models via the OpenAI API (OPENAI_API_KEY), or any
               OpenAI-compatible server through OPENAI_BASE_URL.
  ollama       A local model through Ollama (OLLAMA_BASE_URL).
  echo         A stand-in that needs no model, for proving the wiring.

Every provider answers the same two calls (see base.Provider): one reply, or
the same reply as a stream of events the app renders as it arrives.
"""
from __future__ import annotations

from ..config import Config
from .base import Provider, ProviderError


def build(cfg: Config) -> Provider:
    if cfg.provider == "echo":
        from .echo import EchoProvider

        return EchoProvider()
    if cfg.provider == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.provider == "claude-code":
        from .claude_code import ClaudeCodeProvider

        return ClaudeCodeProvider(cfg)
    if cfg.provider == "openai":
        from .openai import OpenAIProvider

        return OpenAIProvider(cfg)
    if cfg.provider == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(cfg)
    raise SystemExit(f"Unknown provider {cfg.provider!r}")


__all__ = ["Provider", "ProviderError", "build"]
