#!/bin/sh
set -eu

DATA_DIR="${LINKEDIN_GATEWAY_DATA_DIR:-/data}"
PORT="${PORT:-10000}"

mkdir -p "$DATA_DIR"
mkdir -p "$DATA_DIR/accounts"

export LINKEDIN_GATEWAY_PORT="$PORT"

cd /app/remote-gateway

exec uvicorn app:app \
    --host 0.0.0.0 \
    --port "$PORT"
