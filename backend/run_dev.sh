#!/usr/bin/env sh
# Loads backend/.env (if present) and starts the API with auto-reload.
set -a; [ -f .env ] && . ./.env; set +a
exec .venv/bin/uvicorn app.main:app --reload --port 8000
