#!/usr/bin/env python3
"""Delete the autonomous CEO managed agent.

Removes only the agent configuration; past interactions persist on the platform.
Env: GEMINI_API_KEY, AGENT_ID (default "ai-ceo")
"""
from __future__ import annotations

import os
import sys

from google import genai


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: set GEMINI_API_KEY", file=sys.stderr)
        return 1
    agent_id = os.environ.get("AGENT_ID", "ai-ceo")
    client = genai.Client()
    client.agents.delete(id=agent_id)
    print(f"Deleted agent '{agent_id}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
