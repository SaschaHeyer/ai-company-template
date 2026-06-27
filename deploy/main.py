"""Cloud Run HTTP entrypoint — the hourly trigger.

Cloud Scheduler hits this endpoint once an hour (OIDC-authenticated). It fires exactly one
CEO loop on the Gemini managed-agent runtime by delegating to runner/run_loop.py, then
returns. The heavy lifting happens on Google's managed runtime, NOT here — this container
is just the cron trigger, so it can stay tiny.

Run locally:  PORT=8080 gunicorn --timeout 3600 deploy.main:app
"""
from __future__ import annotations

import os
import sys
import traceback

from flask import Flask, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "runner"))
import run_loop  # noqa: E402

app = Flask(__name__)


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, agent=os.environ.get("AGENT_ID", "ai-ceo"))


@app.route("/", methods=["GET", "POST"])
def trigger():
    """Fire one loop. Cloud Scheduler invokes this hourly."""
    try:
        rc = run_loop.main()
        return jsonify(ok=(rc == 0), returncode=rc), (200 if rc == 0 else 500)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return jsonify(ok=False, error=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
