#!/usr/bin/env bash
# =============================================================================
# start.sh — Container entrypoint for RunPod serverless
#
# This script ONLY starts the handler. All models are pre-downloaded into
# the image at build time by install_models.sh.  No network downloads occur
# here. Fast, predictable, production-safe startup.
# =============================================================================
set -euo pipefail

export PYTHONUNBUFFERED=1

cd /workspace/app
exec python -u handler.py
