"""OpenAI and Ollama over a fake HTTP transport: the wire parsing, the errors, the body."""
import json

import httpx
import pytest

from app.config import Config
from app.providers.base import ProviderError
from app.providers.ollama import OllamaProvider
from app.providers.openai import OpenAIProvider


def cfg(**over) -> Config:
    base = dict(
        token="x" * 32, state_dir="/tmp", provider="openai", model="gpt-5.1", effort="high", max_tokens=100, timeout=5,
        root_path="", anthropic_key="", openai_key="sk-test", openai_base_url="https://api.openai.com/v1",
        ollama_base_url="http://ollama:11434", claude_code_cmd="claude",
    )
    base.update(over)
    return Config(**base)


async def events(stream):
    return [e async for e in stream]


@pytest.mark.asyncio
async def test_openai_streams_deltas_and_sends_reasoning_effort():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers.get("authorization")
        sse = "\n".join([
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            "data: [DONE]",
            "",
        ])
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    p = OpenAIProvider(cfg(), transport=httpx.MockTransport(handler))
    out = await events(p.stream("q", system="SYS", messages=[{"role": "user", "content": "hi"}], deep=True))
    assert out[0] == {"type": "thinking"}
    assert "".join(e["delta"] for e in out[1:]) == "Hello"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen["body"]["reasoning_effort"] == "high" and seen["body"]["stream"] is True


@pytest.mark.asyncio
async def test_openai_non_reasoning_model_gets_no_effort_field():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\ndata: [DONE]\n')

    p = OpenAIProvider(cfg(model="gpt-4.1-mini"), transport=httpx.MockTransport(handler))
    assert await p.generate("q", messages=[{"role": "user", "content": "hi"}]) == "ok"
    assert "reasoning_effort" not in seen["body"]


@pytest.mark.asyncio
async def test_openai_errors_become_sentences():
    def handler(req):
        return httpx.Response(401, content=b'{"error":{"message":"bad key"}}')

    p = OpenAIProvider(cfg(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="rejected the key"):
        await p.generate("q")


@pytest.mark.asyncio
async def test_ollama_streams_ndjson_until_done():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        lines = [
            {"message": {"role": "assistant", "content": "Good "}, "done": False},
            {"message": {"role": "assistant", "content": "morning"}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True},
            {"message": {"role": "assistant", "content": "IGNORED"}, "done": False},
        ]
        return httpx.Response(200, content="\n".join(json.dumps(l) for l in lines).encode())

    p = OllamaProvider(cfg(provider="ollama", model="llama3.1:8b"), transport=httpx.MockTransport(handler))
    assert await p.generate("q", system="SYS", messages=[{"role": "user", "content": "hi"}]) == "Good morning"
    assert seen["body"]["model"] == "llama3.1:8b" and seen["body"]["options"]["num_predict"] == 100
    assert seen["body"]["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_ollama_missing_model_says_how_to_pull():
    def handler(req):
        return httpx.Response(404, content=b'{"error":"model \'llama3.1:8b\' not found"}')

    p = OllamaProvider(cfg(provider="ollama", model="llama3.1:8b"), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="ollama pull"):
        await p.generate("q")


@pytest.mark.asyncio
async def test_unreachable_is_a_sentence_not_a_trace():
    def handler(req):
        raise httpx.ConnectError("refused")

    p = OllamaProvider(cfg(provider="ollama"), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="Could not reach Ollama"):
        await p.generate("q")
