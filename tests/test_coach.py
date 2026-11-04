from app import coach
from app.models import ChatMessage, HealthSnapshot


def test_rail_fires_on_red_flags_only():
    assert coach.needs_escalation("I have chest pain since this morning")
    assert coach.needs_escalation("I feel short of breath at rest")
    assert not coach.needs_escalation("I was short of breath after sprints")
    assert not coach.needs_escalation("how did I sleep this week?")


def test_prompt_uses_phone_system_when_given():
    snap = HealthSnapshot(date="2026-11-04", steps=8000, sleepMinutes=450)
    msgs = [ChatMessage(role="user", content="hi")]
    own = coach.build_prompt(msgs, snap, [], own_system=True)
    theirs = coach.build_prompt(msgs, snap, [], own_system=False)
    assert coach.SYSTEM in own and coach.SYSTEM not in theirs
    assert "steps 8000" in theirs and "sleep 7h30" in theirs
    assert theirs.rstrip().endswith("Coach:")
