#!/usr/bin/env python3
"""Create (or recreate) the autonomous CEO managed agent on the Gemini runtime.

This is the managed-agent equivalent of the Claude Code CEO's CLAUDE.md: it registers a
custom agent whose `system_instruction` is the durable CEO brief. The agent is invoked once
per hour by runner/run_loop.py.

We deliberately keep `base_environment` minimal here. The workspace (git memory) and the
credentials are mounted *per loop* by the runner, because the workspace changes every hour
and the GCP token is short-lived. See runner/run_loop.py.

Requires: google-genai >= 2.3.0   (pip install -U google-genai)
Env:      GEMINI_API_KEY, AGENT_ID (default "ai-ceo"), BASE_AGENT
Docs:     https://ai.google.dev/gemini-api/docs/custom-agents.md.txt
"""
from __future__ import annotations

import os
import pathlib
import sys

from google import genai

HERE = pathlib.Path(__file__).resolve().parent
AGENT_ID = os.environ.get("AGENT_ID", "ai-ceo")
BASE_AGENT = os.environ.get("BASE_AGENT", "antigravity-preview-05-2026")
SYSTEM_INSTRUCTION = (HERE / "system_instruction.md").read_text(encoding="utf-8")


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: set GEMINI_API_KEY", file=sys.stderr)
        return 1

    client = genai.Client()  # reads GEMINI_API_KEY from the environment

    # Agents have no in-place update / versioning yet, so make this idempotent:
    # delete an existing agent with the same id, then create fresh.
    try:
        client.agents.delete(id=AGENT_ID)
        print(f"Deleted existing agent '{AGENT_ID}' (recreating).")
    except Exception:
        pass  # didn't exist — fine

    agent = client.agents.create(
        id=AGENT_ID,
        base_agent=BASE_AGENT,
        description="Autonomous CEO — runs an availability-alert business hourly, one loop at a time.",
        system_instruction=SYSTEM_INSTRUCTION,
        # Default tools (code_execution, google_search, url_context) are exactly what the
        # CEO needs. The repo + credentials are mounted per-loop by the runner, so we do not
        # bake a base_environment here.
    )

    print(f"Created managed agent: {getattr(agent, 'id', AGENT_ID)}")
    print(f"  base_agent: {BASE_AGENT}")
    print(f"  system_instruction: {len(SYSTEM_INSTRUCTION):,} chars from agent/system_instruction.md")
    print("\nNext: configure runner/.env and run  python runner/run_loop.py  for a single loop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
