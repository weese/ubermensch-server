"""
UberMensch server.

Sits between the UberMensch app and a language model. Small on purpose: it
authenticates, keeps a short history of daily summaries, builds a fallback
prompt, and applies the safety rail. The intelligence is the provider behind
it, chosen with UBERMENSCH_PROVIDER.
"""
from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import coach
from .config import VERSION, load
from .models import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    PingResponse,
    SnapshotRequest,
    SnapshotResponse,
)
from .providers import ProviderError, build
from .store import Store

log = logging.getLogger("ubermensch")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
cfg = load()
bearer = HTTPBearer(auto_error=False)

ESCALATION_NOTE = (
    "That is not something to work through with an app. Please contact a "
    "doctor now, or your local emergency number if it is severe or sudden."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = Store(cfg.db_path)
    app.state.provider = build(cfg)
    log.info("ubermensch-server %s up: provider=%s model=%s effort=%s root_path=%s", VERSION, cfg.provider, cfg.model or "(default)", cfg.effort, cfg.root_path or "/")
    yield


# root_path makes the OpenAPI document and docs links right behind a reverse
# proxy that serves this under a prefix (e.g. /ubermensch). The routes
# themselves are unchanged: the proxy strips the prefix.
app = FastAPI(title="UberMensch server", version=VERSION, lifespan=lifespan, root_path=cfg.root_path)


def require_token(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    # compare_digest, not ==, so a wrong token cannot be found a character at
    # a time by timing the response.
    if creds is None or not hmac.compare_digest(creds.credentials, cfg.token):
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Unauthenticated liveness: what runs here, never any data or secret."""
    return HealthResponse(ok=True, version=VERSION, provider=cfg.provider, model=cfg.model or "default")


@app.post("/v1/ping", response_model=PingResponse)
async def ping(_: None = Depends(require_token)) -> PingResponse:
    return PingResponse(ok=True, version=VERSION, provider=cfg.provider, model=cfg.model or "default")


@app.post("/v1/snapshot", response_model=SnapshotResponse)
async def put_snapshot(req: SnapshotRequest, request: Request, _: None = Depends(require_token)) -> SnapshotResponse:
    request.app.state.store.put(req.snapshot)
    return SnapshotResponse(stored=True)


def _prepare(req: ChatRequest, request: Request) -> tuple[bool, str]:
    if not req.messages:
        raise HTTPException(status_code=400, detail="no messages")
    if req.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="last message must be from the user")
    # Keep the snapshot that came with the question, so history is complete
    # even if the app never synced it separately.
    store: Store = request.app.state.store
    if req.snapshot is not None:
        store.put(req.snapshot)
    # The rail fires on the user's own words before the model is consulted.
    # A model instructed to escalate usually will, but "usually" is not a
    # safety property, and this path must not depend on the model behaving.
    escalate = coach.needs_escalation(req.messages[-1].content)
    prompt = coach.build_prompt(req.messages, req.snapshot, store.recent(), own_system=not req.system)
    return escalate, prompt


@app.post("/v1/chat", response_model=ChatResponse)
async def post_chat(req: ChatRequest, request: Request, _: None = Depends(require_token)) -> ChatResponse:
    escalate, prompt = _prepare(req, request)
    try:
        reply = await request.app.state.provider.generate(
            prompt, system=req.system, messages=[m.model_dump() for m in req.messages], deep=req.deep
        )
    except ProviderError as exc:
        log.warning("provider failed: %s", exc)
        if escalate:
            # Never swallow an urgent message behind a backend error.
            return ChatResponse(reply=ESCALATION_NOTE, escalate=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if escalate:
        reply = f"{ESCALATION_NOTE}\n\n{reply}"
    return ChatResponse(reply=reply, escalate=escalate)


@app.post("/v1/chat/stream")
async def post_chat_stream(req: ChatRequest, request: Request, _: None = Depends(require_token)) -> StreamingResponse:
    """
    The same answer as /v1/chat, written as it is generated: one JSON object
    per line - {"type": "thinking"}, {"type": "text", "delta": ...}, then
    {"type": "done", "escalate": bool} or {"type": "error", "message": ...}.
    """
    escalate, prompt = _prepare(req, request)
    provider = request.app.state.provider

    async def events():
        def line(o: dict) -> str:
            return json.dumps(o, ensure_ascii=False) + "\n"

        if escalate:
            yield line({"type": "text", "delta": f"{ESCALATION_NOTE}\n\n"})
        try:
            async for ev in provider.stream(prompt, system=req.system, messages=[m.model_dump() for m in req.messages], deep=req.deep):
                yield line(ev)
        except ProviderError as exc:
            log.warning("provider failed: %s", exc)
            if not escalate:
                yield line({"type": "error", "message": str(exc)})
                return
        yield line({"type": "done", "escalate": escalate})

    # No proxy buffering: the point is that each line arrives as it is written.
    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
