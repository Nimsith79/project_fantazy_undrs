#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

cd /workspace/app
exec python -u handler.py
