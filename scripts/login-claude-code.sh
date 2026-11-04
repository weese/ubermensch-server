#!/usr/bin/env bash
# Connect the coach to Claude on a Claude subscription, via Claude Code.
#
# Claude Code runs inside the ubermensch container and the login is made
# there too - nothing is installed or logged in on the host. Its credentials
# land in CLAUDE_CODE_DIR (default ./claude; mode 700, uid 1000), the only
# directory the container can see. Idempotent: re-run after a logout or an
# expired login. Nothing secret is printed.
#
#   ./scripts/login-claude-code.sh          # from the repository directory
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "No .env here. Copy .env.example to .env first."; exit 1; }
DIR=$(grep -E '^CLAUDE_CODE_DIR=' .env | cut -d= -f2- || true)
DIR=${DIR:-./claude}
PORT=$(grep -E '^PORT=' .env | cut -d= -f2- || true); PORT=${PORT:-8099}
BIND=$(grep -E '^BIND_ADDR=' .env | cut -d= -f2- || true); BIND=${BIND:-127.0.0.1}

# uid 1000 is the container's user; docker would otherwise create this as root.
install -d -m 700 "$DIR" && { chown 1000:1000 "$DIR" 2>/dev/null || sudo chown 1000:1000 "$DIR"; }
docker compose up -d --build >/dev/null

if ! docker compose exec ubermensch claude auth status >/dev/null 2>&1; then
    [ -t 0 ] || { echo "Not logged in, and no terminal for the login. Run this from an interactive shell (ssh -t)."; exit 1; }
    echo "Log in with the Claude account whose subscription the coach should use."
    docker compose exec -it ubermensch claude auth login
fi
docker compose exec ubermensch claude auth status >/dev/null 2>&1 || { echo "Still not logged in."; exit 1; }
echo "Claude Code is logged in."

# Flip the provider to claude-code and restart.
sed -i.bak 's/^UBERMENSCH_PROVIDER=.*/UBERMENSCH_PROVIDER=claude-code/' .env && rm -f .env.bak
docker compose up -d >/dev/null
for _ in $(seq 1 30); do curl -s -o /dev/null -w '%{http_code}' "http://$BIND:$PORT/v1/health" | grep -q 200 && break; sleep 1; done

# Smoke test: the model answers a trivial prompt through the whole chain.
T=$(grep -E '^UBERMENSCH_TOKEN=' .env | cut -d= -f2-)
printf 'coach reply: '
curl -s -X POST -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Reply with the single word OK."}],"snapshot":null}' \
  "http://$BIND:$PORT/v1/chat" | head -c 300; echo
echo "Done. In the app: You -> Settings -> Coach engine -> Server, with this server's address and the token from .env."
