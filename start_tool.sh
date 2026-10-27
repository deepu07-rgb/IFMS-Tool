#!/usr/bin/env bash
# Retained engine: Phase3-Full-Stable. Diagnostics: /api/version /api/v3/health_check
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install --no-deps -r requirements.lock
fi
exec .venv/bin/python launch.py
