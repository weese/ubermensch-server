"""Wire types. These mirror the TypeScript in the app (app/src/api/client.ts) - keep them in step."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthSnapshot(BaseModel):
    date: str
    steps: int | None = None
    restingHeartRate: int | None = None
    averageHeartRate: int | None = None
    activeEnergyKcal: int | None = None
    sleepMinutes: int | None = None
    weightKg: float | None = None
    unavailable: list[str] = Field(default_factory=list)
    source: Literal["healthkit", "health-connect", "none"] = "none"


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=100)
    snapshot: HealthSnapshot | None = None
    # Assembled on the phone: memory, goals, plan, compressed history. When
    # present it is the authoritative context; the server-side prompt is
    # only the fallback for clients that do not send one.
    system: str | None = Field(default=None, max_length=60000)
    # "Think deeper": a request for the provider's higher reasoning setting.
    deep: bool = False


class ChatResponse(BaseModel):
    reply: str
    escalate: bool = False


class SnapshotRequest(BaseModel):
    snapshot: HealthSnapshot


class SnapshotResponse(BaseModel):
    stored: bool


class PingResponse(BaseModel):
    ok: bool
    version: str
    provider: str | None = None
    model: str | None = None


class HealthResponse(BaseModel):
    """Unauthenticated: enough to see that the service is up and what it runs, never a secret."""
    ok: bool
    service: str = "ubermensch-server"
    version: str
    provider: str
    model: str
