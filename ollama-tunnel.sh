#!/usr/bin/env bash
set -euo pipefail

OPENPORT_URL="https://openport.io/l/26996/sY93JhaTxu1kSqFp"
SSH_USER="edoardo.tedesco@openport.io"
SSH_PORT=26996
LOCAL_PORT=11435
REMOTE_PORT=11434

# Load password from .env.prod if not already set
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${OPENPORT_PASSWORD:-}" ] && [ -f "$SCRIPT_DIR/.env.prod" ]; then
    OPENPORT_PASSWORD=$(grep -oP '^OPENPORT_PASSWORD=\K.*' "$SCRIPT_DIR/.env.prod")
fi

# Check if tunnel is already running
if ss -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT}" || netstat -tlnp 2>/dev/null | grep -q ":${LOCAL_PORT}"; then
    echo "Tunnel already active on port ${LOCAL_PORT}."
    exit 0
fi

# sshpass is needed to pass password non-interactively
if ! command -v sshpass &>/dev/null; then
    echo "Installing sshpass..."
    apt-get update -qq && apt-get install -y -qq sshpass
fi

# Activate the openport.io endpoint
echo "Activating openport.io tunnel..."
curl -sf "$OPENPORT_URL" || echo "Warning: openport.io request failed (may already be active)"

sleep 2

# Create SSH tunnel: local 11435 -> remote localhost:11434 (Ollama)
echo "Creating SSH tunnel (port ${LOCAL_PORT} -> ${REMOTE_PORT})..."
sshpass -p "${OPENPORT_PASSWORD}" ssh \
    -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -p "$SSH_PORT" \
    -N -f \
    -L "${LOCAL_PORT}:localhost:${REMOTE_PORT}" \
    "$SSH_USER"

echo "Tunnel active! Ollama reachable at http://localhost:${LOCAL_PORT}"
echo "Test: curl http://localhost:${LOCAL_PORT}/api/tags"
