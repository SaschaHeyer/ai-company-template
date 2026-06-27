#!/usr/bin/env python3
"""cancel_loop.py — cancel a running CEO loop (managed-agent interaction) by id.

Ctrl-C in run_loop.py now cancels the server-side run automatically. Use THIS from another shell when
you already killed the runner, or to cancel a loop whose id you captured. Each streamed run prints its
id at the top (`[interaction <id> | sandbox …]`). There is no `interactions.list()`, so you MUST have
the id — without it a run can only finish/time out on its own.

Usage:
  GEMINI_API_KEY=$(gcloud secrets versions access latest --secret=gemini-api-key --project=$GCP_PROJECT) \
    python3 runner/cancel_loop.py <interaction_id>
"""
import sys

from google import genai


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python3 runner/cancel_loop.py <interaction_id>", file=sys.stderr)
        return 2
    iid = sys.argv[1]
    try:
        ix = genai.Client().interactions.cancel(id=iid)
        print(f"cancel requested for {iid} — status: {getattr(ix, 'status', '?')}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"cancel failed for {iid}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
