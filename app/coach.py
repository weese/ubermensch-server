"""
Prompt construction and the safety rail.

The coach is deliberately framed as a *fitness and habit* assistant working
from the user's own numbers. It is not a diagnostic tool, and the prompt says
so, because an LLM handed heart-rate data will otherwise happily speculate
about arrhythmia.
"""
from __future__ import annotations

import re

from .models import ChatMessage, HealthSnapshot

SYSTEM = """You are UberMensch, a personal fitness and wellbeing coach running \
on a server the user runs themselves. You see a daily summary of their activity, sleep, \
heart rate and weight, taken from Apple Health or Health Connect.

How to answer:
- Be concrete and refer to the actual numbers you were given.
- Where a number is missing, say so rather than guessing or assuming zero.
- Give practical, incremental suggestions about training, sleep and habits.
- Keep answers short. Two or three paragraphs at most.
- One person's data is noisy. Prefer trends across days over single readings.

Limits you must respect:
- You are not a doctor and this is not a medical device. Do not diagnose, do \
not name conditions as conclusions, and do not give medication, dosage or \
supplement-protocol advice.
- If the user describes symptoms that could be urgent - chest pain, fainting, \
breathlessness at rest, a sudden severe headache, thoughts of self-harm - stop \
coaching and tell them plainly to seek medical help now.
- If data looks alarming but the user reports no symptoms, say what you notice \
and suggest they raise it with a clinician. Do not speculate about causes.
- Never claim certainty you do not have."""

# Deliberately short and high-signal. A long keyword list produces false
# positives, and an escalation banner that fires constantly gets ignored -
# which is worse than not having one.
_RED_FLAGS = re.compile(
    r"\b("
    r"chest pain|crushing chest|tightness in my chest"
    r"|can'?t breathe|short of breath at rest|breathless at rest"
    r"|fainted|fainting|passed out|blacked out"
    r"|worst headache|sudden severe headache"
    r"|coughing blood|vomiting blood|blood in my stool"
    r"|numb on one side|slurred speech|face drooping"
    r"|kill myself|end my life|suicidal|self-harm"
    r")\b",
    re.IGNORECASE,
)


def needs_escalation(text: str) -> bool:
    return bool(_RED_FLAGS.search(text))


def describe(snap: HealthSnapshot | None) -> str:
    if snap is None:
        return "No health summary was supplied with this question."

    known: list[str] = []
    if snap.steps is not None:
        known.append(f"steps {snap.steps}")
    if snap.sleepMinutes is not None:
        h, m = divmod(snap.sleepMinutes, 60)
        known.append(f"sleep {h}h{m:02d}")
    if snap.restingHeartRate is not None:
        known.append(f"resting HR {snap.restingHeartRate} bpm")
    if snap.averageHeartRate is not None:
        known.append(f"average HR {snap.averageHeartRate} bpm")
    if snap.activeEnergyKcal is not None:
        known.append(f"active energy {snap.activeEnergyKcal} kcal")
    if snap.weightKg is not None:
        known.append(f"weight {snap.weightKg} kg")

    line = f"{snap.date}: " + (", ".join(known) if known else "nothing recorded")
    if snap.unavailable:
        line += f" (no data for: {', '.join(snap.unavailable)})"
    return line


def build_prompt(
    messages: list[ChatMessage],
    snapshot: HealthSnapshot | None,
    history: list[HealthSnapshot],
    *,
    own_system: bool = True,
) -> str:
    """Flatten everything into one prompt string.

    A single string rather than a role array because the harness is driven as
    a command-line program; if it later exposes a structured chat API this is
    the one function to change.
    """
    # When the phone sends its own instructions they are the system prompt,
    # and this server's older ones would only contradict them (length,
    # format). The medical limits are in both; the escalation rail is code.
    parts = [SYSTEM, ""] if own_system else []
    parts += ["## Today", describe(snapshot)]

    # Trend context: the prompt tells the model to prefer trends, so it has to
    # actually be given some.
    trend = [h for h in history if snapshot is None or h.date != snapshot.date]
    if trend:
        parts += ["", "## Recent days", *[describe(h) for h in trend[-13:]]]

    parts += ["", "## Conversation"]
    for m in messages[-20:]:
        who = "User" if m.role == "user" else "Coach"
        parts.append(f"{who}: {m.content}")
    parts.append("Coach:")
    return "\n".join(parts)
