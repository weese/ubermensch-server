"""The app's system prompt: a static part providers cache, and a per-turn part after the marker."""
from app.providers.anthropic import _system_blocks
from app.providers.base import SYSTEM_SPLIT, joined_system, split_system
from app.providers.claude_code import PER_TURN_HEAD, ClaudeCodeProvider
from tests.test_http_providers import cfg

SYSTEM = f"Instructions and the app guide.\n\n{SYSTEM_SPLIT}\n\nToday: 8000 steps."


def test_split_and_join():
    assert split_system(SYSTEM) == ("Instructions and the app guide.", "Today: 8000 steps.")
    assert split_system("no marker") == ("no marker", "")
    assert split_system(None) == (None, "")
    assert joined_system(SYSTEM) == "Instructions and the app guide.\n\nToday: 8000 steps."
    assert joined_system("no marker") == "no marker"


def test_anthropic_caches_only_the_static_block():
    blocks = _system_blocks(SYSTEM)
    assert blocks[0] == {"type": "text", "text": "Instructions and the app guide.", "cache_control": {"type": "ephemeral"}}
    assert blocks[1] == {"type": "text", "text": "Today: 8000 steps."}
    assert len(_system_blocks("no marker")) == 1


def test_claude_code_puts_the_per_turn_part_in_front_of_the_conversation(tmp_path):
    p = ClaudeCodeProvider(cfg(provider="claude-code", model=""), cwd=str(tmp_path))
    argv, stdin = p._argv_for([], SYSTEM, "User: hi\nCoach:")
    assert argv[argv.index("--system-prompt") + 1] == "Instructions and the app guide."
    assert stdin == f"{PER_TURN_HEAD}\nToday: 8000 steps.\n\nUser: hi\nCoach:"
    argv, stdin = p._argv_for([], "no marker", "User: hi")
    assert argv[argv.index("--system-prompt") + 1] == "no marker" and stdin == "User: hi"
