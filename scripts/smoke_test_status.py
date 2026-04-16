#!/usr/bin/env python3
"""Smoke-test the deployed Cloud Run service status endpoint."""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    response = os.environ.get("RESPONSE", "")
    project_id = os.environ.get("PROJECT_ID", "")

    try:
        data = json.loads(response)
    except json.JSONDecodeError as exc:
        print(f"Smoke test failed: invalid JSON: {exc}")
        return 1

    required = ["project", "ai_backend", "gemini_configured"]
    missing = [key for key in required if key not in data]
    if missing:
        print(f"Smoke test failed: missing keys {missing}")
        return 1

    if data.get("project") != project_id:
        print(f"Smoke test failed: project mismatch {data.get('project')!r}")
        return 1

    if not data.get("gemini_configured"):
        print("Smoke test failed: Gemini not configured")
        return 1

    print("Smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
