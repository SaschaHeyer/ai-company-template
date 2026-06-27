#!/usr/bin/env python3
"""List every managed agent on the account.

agents.list() returns a response whose `.agents` field is the list of Agent objects
(iterating the response itself yields field tuples, not agents — use `.agents`).

Env: GEMINI_API_KEY
Usage: python agent/list_agents.py
"""
from __future__ import annotations

import os
import sys

from google import genai


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: set GEMINI_API_KEY", file=sys.stderr)
        return 1
    client = genai.Client()

    agents = []
    page = client.agents.list()
    while True:
        agents.extend(getattr(page, "agents", None) or [])
        token = getattr(page, "next_page_token", None)
        if not token:
            break
        page = client.agents.list(config={"page_token": token})

    print(f"{len(agents)} managed agent(s):")
    for a in agents:
        print(f"  - {a.id}   base={a.base_agent}   {a.description or ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
