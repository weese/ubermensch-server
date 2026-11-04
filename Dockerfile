# syntax=docker/dockerfile:1.7
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Claude Code, for the claude-code provider. Pinned by version and sha256 so a
# CLI cannot change under you. It is a single native binary from npm's
# linux-x64 package, so the image needs no Node. To upgrade, bump both:
#   npm pack @anthropic-ai/claude-code-linux-x64@<v> && shasum -a 256 *.tgz
# Build with --build-arg WITH_CLAUDE_CODE=0 to leave it out.
ARG WITH_CLAUDE_CODE=1
ARG CLAUDE_CODE_VERSION=2.1.317
ARG CLAUDE_CODE_SHA256=c33bff413c33274e404cd57378300c6a389558a4e757f9af64539326d1c53fb2
ADD --checksum=sha256:${CLAUDE_CODE_SHA256} \
    https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-${CLAUDE_CODE_VERSION}.tgz /tmp/claude.tgz
RUN if [ "$WITH_CLAUDE_CODE" = "1" ]; then \
      tar -xzf /tmp/claude.tgz -C /tmp package/claude \
      && install -m 755 /tmp/package/claude /usr/local/bin/claude \
      && rm -rf /tmp/package; \
    fi && rm -f /tmp/claude.tgz
# The autoupdater is off so the pin holds.
ENV DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

COPY app ./app

# Runs as a non-root user. The state and credentials directories must be
# owned by this uid on the host, or docker creates them as root and the
# container cannot write.
RUN useradd --uid 1000 --create-home ubermensch
USER ubermensch

EXPOSE 8099
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8099"]
