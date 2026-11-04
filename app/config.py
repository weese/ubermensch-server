"""
Configuration, all from the environment - nothing secret in the image.

Every knob has a plain default except the token, which must be set: this
service relays a person's health summary to a model, and a guessable door is
not a soft failure. Older installs used UBERMENSCH_HARNESS* names; they are
still read, so an existing .env keeps working.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

VERSION = "1.0.0"

PROVIDERS = ("anthropic", "claude-code", "openai", "ollama", "echo")

# Which model to use when none is named, per provider.
DEFAULT_MODEL = {
    "anthropic": "claude-opus-5-5",
    "claude-code": "",  # Claude Code's own default for the account
    "openai": "gpt-5.1",
    "ollama": "llama3.1:8b",
    "echo": "",
}


def _env(*names: str, default: str = "") -> str:
    """The first set variable among `names` - newest name first, old aliases after."""
    for n in names:
        v = os.environ.get(n)
        if v is not None and v.strip():
            return v.strip()
    return default


@dataclass(frozen=True)
class Config:
    token: str
    state_dir: str
    provider: str
    model: str
    effort: str
    max_tokens: int
    timeout: int
    root_path: str
    # provider specifics
    anthropic_key: str
    openai_key: str
    openai_base_url: str
    ollama_base_url: str
    claude_code_cmd: str

    @property
    def db_path(self) -> str:
        return os.path.join(self.state_dir, "ubermensch.db")


def load() -> Config:
    token = _env("UBERMENSCH_TOKEN")
    if len(token) < 24:
        raise SystemExit(
            "UBERMENSCH_TOKEN must be set and at least 24 characters. "
            "Generate one with:  openssl rand -hex 32"
        )
    provider = _env("UBERMENSCH_PROVIDER", "UBERMENSCH_HARNESS", default="echo").lower()
    if provider == "claude":  # the old name for the Claude Code mode
        provider = "claude-code"
    if provider not in PROVIDERS:
        raise SystemExit(f"UBERMENSCH_PROVIDER={provider!r}; expected one of {', '.join(PROVIDERS)}.")
    model = _env("UBERMENSCH_MODEL", default=DEFAULT_MODEL[provider])
    root_path = _env("UBERMENSCH_ROOT_PATH").rstrip("/")
    if root_path and not root_path.startswith("/"):
        root_path = "/" + root_path
    return Config(
        token=token,
        state_dir=_env("UBERMENSCH_STATE", default="/var/lib/ubermensch"),
        provider=provider,
        model=model,
        # "high" suits a coach reasoning over months of data; "medium" is faster.
        effort=_env("UBERMENSCH_EFFORT", default="high").lower(),
        max_tokens=int(_env("UBERMENSCH_MAX_TOKENS", default="4096")),
        # Under the app's own 170 s, so a slow answer fails here with a message.
        timeout=int(_env("UBERMENSCH_TIMEOUT", "UBERMENSCH_HARNESS_TIMEOUT", default="160")),
        root_path=root_path,
        anthropic_key=_env("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        openai_key=_env("OPENAI_API_KEY"),
        openai_base_url=_env("OPENAI_BASE_URL", default="https://api.openai.com/v1").rstrip("/"),
        ollama_base_url=_env("OLLAMA_BASE_URL", default="http://host.docker.internal:11434").rstrip("/"),
        claude_code_cmd=_env("CLAUDE_CODE_CMD", "UBERMENSCH_HARNESS_CMD", default="claude"),
    )
