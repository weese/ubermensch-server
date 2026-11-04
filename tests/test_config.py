import os

import pytest

from app import config


def _load(monkeypatch, **env):
    for k in ("UBERMENSCH_PROVIDER", "UBERMENSCH_HARNESS", "UBERMENSCH_MODEL", "UBERMENSCH_ROOT_PATH", "UBERMENSCH_HARNESS_TIMEOUT", "UBERMENSCH_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config.load()


def test_old_harness_names_still_work(monkeypatch):
    c = _load(monkeypatch, UBERMENSCH_HARNESS="claude", UBERMENSCH_HARNESS_TIMEOUT="99")
    assert c.provider == "claude-code" and c.timeout == 99


def test_new_name_wins_over_old(monkeypatch):
    c = _load(monkeypatch, UBERMENSCH_PROVIDER="ollama", UBERMENSCH_HARNESS="claude")
    assert c.provider == "ollama" and c.model == "llama3.1:8b"


def test_root_path_is_normalised(monkeypatch):
    assert _load(monkeypatch, UBERMENSCH_ROOT_PATH="ubermensch/").root_path == "/ubermensch"
    assert _load(monkeypatch).root_path == ""


def test_unknown_provider_refuses_to_start(monkeypatch):
    with pytest.raises(SystemExit):
        _load(monkeypatch, UBERMENSCH_PROVIDER="gemini")


def test_short_token_refuses_to_start(monkeypatch):
    monkeypatch.setenv("UBERMENSCH_TOKEN", "short")
    with pytest.raises(SystemExit):
        config.load()
    monkeypatch.setenv("UBERMENSCH_TOKEN", os.environ.get("UBERMENSCH_TOKEN") or "test-token-test-token-test-token")
