# UberMensch server

The optional server half of UberMensch, the personal
health coach app. The app works entirely on the phone; this service exists
for one reason: to put a **bigger model of your choice** behind the coach,
running where you decide, on your terms.

```
UberMensch app  --HTTPS-->  ubermensch-server  -->  the model you configured
   (your phone)              (your machine)          Claude · ChatGPT · Ollama · Claude Code
```

The app assembles the whole coaching context on the phone - goals, plan,
facts about you, a compressed history of daily aggregates - and sends it
with each question. The server relays it to the model and streams the answer
back. It keeps a short history of daily summaries (six aggregates per day,
never raw samples) and nothing else.

## Providers

| `UBERMENSCH_PROVIDER` | What answers | Needs |
|---|---|---|
| `anthropic` | Claude via the Messages API (default `claude-opus-5-5`, adaptive thinking) | `ANTHROPIC_API_KEY` |
| `claude-code` | Claude Code headless on a **Claude subscription**, no API key | a one-time login in the container |
| `openai` | ChatGPT models via the OpenAI API (default `gpt-5.1`), or any OpenAI-compatible server | `OPENAI_API_KEY`, or `OPENAI_BASE_URL` |
| `ollama` | A local model through [Ollama](https://ollama.com) (default `llama3.1:8b`) | Ollama reachable from the container |
| `echo` | A stand-in that repeats the question; no model | nothing |

All five speak the same API to the app, so switching is one line in `.env`.

## Install

Needs Docker with the compose plugin. Any Linux box, a Mac, a NAS.

```bash
git clone <this repository> ubermensch-server && cd ubermensch-server
cp .env.example .env
openssl rand -hex 32          # paste the result as UBERMENSCH_TOKEN in .env
docker compose up -d --build
curl http://127.0.0.1:8099/v1/health
```

That runs the `echo` provider on the loopback address. Then pick a provider:

**Claude with an API key**
```
UBERMENSCH_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**Claude on your subscription, no key**
```bash
./scripts/login-claude-code.sh      # interactive: prints a URL, asks for the code
```
Claude Code is pinned inside the image by version and checksum and logs in
from inside the container; the credentials land in `./claude` (uid 1000,
mode 700) and are refreshed there. Nothing is installed on the host.

**ChatGPT**
```
UBERMENSCH_PROVIDER=openai
OPENAI_API_KEY=sk-...
UBERMENSCH_MODEL=gpt-5.1          # or any chat model; reasoning models get UBERMENSCH_EFFORT
```
Any OpenAI-compatible server works through `OPENAI_BASE_URL` (LM Studio,
vLLM, OpenRouter, Groq).

**Ollama**
```
UBERMENSCH_PROVIDER=ollama
UBERMENSCH_MODEL=llama3.1:8b      # pulled on the Ollama side: ollama pull llama3.1:8b
OLLAMA_BASE_URL=http://host.docker.internal:11434
```
That default reaches an Ollama running on the host. For an Ollama of its
own: `docker compose --profile ollama up -d`, set
`OLLAMA_BASE_URL=http://ollama:11434`, and pull a model once with
`docker compose exec ollama ollama pull llama3.1:8b`. A coach reasoning over
months of data wants a capable model; 8B is the floor, not the target.

After any change to `.env`: `docker compose up -d`.

## Reaching it from the phone

The app needs a URL and the token. Three ways, safest first:

1. **A TLS reverse proxy** on a name you own. `deploy/nginx-subpath.conf.example`
   serves it under `https://example.org/ubermensch` next to whatever else
   the site hosts; set `UBERMENSCH_ROOT_PATH=/ubermensch` so `/docs` works.
   Keep `BIND_ADDR=127.0.0.1`.
2. **A VPN** (WireGuard, Tailscale): set `BIND_ADDR` to the VPN address and
   use `http://<vpn-address>:8099`.
3. **The LAN only**: `BIND_ADDR` to the LAN address. Works at home, not away.

Do not forward port 8099 from the internet without TLS. The token protects
the API, but the context the app sends is your health summary.

## In the UberMensch app

You → Settings → Coach engine → **Server**. Enter the address (for example
`https://example.org/ubermensch` or `http://10.0.0.5:8099`) and the token,
tap **Check** - it calls `/v1/ping` - then agree to sending your coaching
context and save. Every question in Coach now goes to this server, streamed
word by word; the answer may end with an actions block that the app checks
against its own schemas and applies (a moved session, a proposed goal).

Switch back to **This iPhone** or **Apple's cloud** at any time; the server
keeps nothing the app needs.

## API

All under `/v1`, JSON, `Authorization: Bearer <token>` except `/v1/health`.

| Method, path | Purpose |
|---|---|
| `GET /v1/health` | Liveness: version, provider, model. No secrets, no auth. |
| `POST /v1/ping` | Auth check; the app's **Check** button. |
| `POST /v1/snapshot` | Store one day's aggregates `{snapshot}`. |
| `POST /v1/chat` | `{messages, snapshot?, system?, deep?}` → `{reply, escalate}` in one piece. |
| `POST /v1/chat/stream` | Same input; NDJSON events: `thinking`, `text` (`delta`), then `done` or `error`. |

`system` is the context the app assembled; when present it is the whole
system prompt. `deep` asks the provider for one step more reasoning
(Anthropic and OpenAI reasoning models honour it). Interactive docs at
`/docs`.

**The safety rail is code, not prompt.** Urgent symptom language in the
user's own words (chest pain, fainting, self-harm, ...) is matched by a short
regex before any model is consulted; the reply then opens with a
"see a doctor now" note, and still does if the provider fails. The same rail
exists in the app for the on-device engines.

## Settings reference

| Variable | Default | Meaning |
|---|---|---|
| `UBERMENSCH_TOKEN` | required, ≥ 24 chars | Shared secret with the app. |
| `UBERMENSCH_PROVIDER` | `echo` | `anthropic`, `claude-code`, `openai`, `ollama`, `echo`. |
| `UBERMENSCH_MODEL` | per provider | Model name. |
| `UBERMENSCH_EFFORT` | `high` | `low`/`medium`/`high` (`max` on Anthropic). |
| `UBERMENSCH_MAX_TOKENS` | `4096` | Reply length cap. |
| `UBERMENSCH_TIMEOUT` | `160` | Seconds per answer; keep under the app's 170. |
| `UBERMENSCH_ROOT_PATH` | empty | Prefix when served under a subpath. |
| `BIND_ADDR`, `PORT` | `127.0.0.1`, `8099` | Where Docker publishes it. |
| `STATE_ROOT` | `./state` | SQLite history on the host. |
| `CLAUDE_CODE_DIR` | `./claude` | Claude Code's login on the host. |

The older `UBERMENSCH_HARNESS*` names are still read, so a `.env` from the
first version keeps working (`claude` there means `claude-code` here).

## Running as a service

`deploy/ubermensch-server.service` is a systemd unit that runs
`docker compose up -d --build` from `/opt/ubermensch-server` at boot:

```bash
sudo cp deploy/ubermensch-server.service /etc/systemd/system/
sudo systemctl enable --now ubermensch-server
```

Adjust `WorkingDirectory` if the checkout lives elsewhere.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
UBERMENSCH_TOKEN=$(openssl rand -hex 32) .venv/bin/python -m pytest
UBERMENSCH_TOKEN=... UBERMENSCH_PROVIDER=echo .venv/bin/uvicorn app.main:app --reload --port 8099
```

The tests cover the rail, the prompt, configuration aliases, the HTTP
surface with the echo provider, and the OpenAI and Ollama wire protocols
over a fake transport. Anthropic and Claude Code are exercised by running
them.

## Privacy, in one paragraph

What leaves the phone in server mode is the coaching context the app
assembled: your goals, plan, the facts you gave the coach, daily aggregates
(steps, sleep, heart rate, weight, energy), and the conversation. Raw
samples never leave the phone. The server stores only the daily aggregates,
in a SQLite file you own. Where the context goes from there is the provider
you chose: Anthropic, OpenAI, or nowhere beyond your machine with Ollama.
