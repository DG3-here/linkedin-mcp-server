# syntax=docker/dockerfile:1.7

FROM mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69

ARG UV_VERSION=0.11.12
ARG VERSION=0.16.0

LABEL org.opencontainers.image.title="LinkedIn MCP Server" \
    org.opencontainers.image.description="Remote multi-account LinkedIn MCP server with browser-based LinkedIn sessions." \
    org.opencontainers.image.source="https://github.com/DG3-here/linkedin-mcp-server" \
    org.opencontainers.image.url="https://github.com/DG3-here/linkedin-mcp-server" \
    org.opencontainers.image.version="${VERSION}" \
    io.modelcontextprotocol.server.name="io.github.DG3-here/linkedin-mcp-server"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH=/app/.venv/bin:$PATH

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./

RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src

RUN uv sync --frozen --no-dev \
    && chmod -R a+rX /ms-playwright

COPY remote-gateway ./remote-gateway

RUN uv pip install --python /app/.venv/bin/python \
    -r /app/remote-gateway/requirements.txt

RUN mkdir -p /data \
    && groupadd --system --gid 10001 linkedin-mcp \
    && useradd --system --uid 10001 --gid linkedin-mcp \
        --home-dir /nonexistent linkedin-mcp \
    && chown -R linkedin-mcp:linkedin-mcp /data

COPY start.sh ./start.sh

RUN chmod +x ./start.sh \
    && chown linkedin-mcp:linkedin-mcp /app/start.sh

USER linkedin-mcp

VOLUME ["/data"]

EXPOSE 10000

CMD ["/app/start.sh"]
