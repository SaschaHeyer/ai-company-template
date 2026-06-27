#!/usr/bin/env python3
"""Auth helper for the managed-agent sandbox — PROXY-ONLY model (no key in the sandbox).

You normally fetch and store NOTHING. The runner injects every credential at the egress proxy:
  * *.googleapis.com                  -> the runner's GCP token (Secret Manager, Firestore, IAM)
  * github.com                        -> a GitHub PAT
  * api.resend.com / api.stripe.com / api.cloudflare.com -> the API key
So just call those services over HTTPS and the proxy authenticates you. Send NO Authorization
header to the proxy-injected domains.

Two helpers remain:
  get <name>        Read a Secret Manager secret over REST (proxy injects auth). Use only for a
                    secret that ISN'T already proxy-injected (e.g. stripe-publishable-key).
  gcloud-token      Mint a short-lived access token via the IAM Credentials API (proxy injects
                    auth) for the ONE thing the proxy can't cover: the gcloud / firebase CLI
                    (deploys). A CLI needs a local credential, so before deploying:
                        export CLOUDSDK_AUTH_ACCESS_TOKEN=$(python3 workspace/tools/secrets.py gcloud-token)
                        gcloud config set project YOUR_PROJECT
                    then gcloud / firebase work. Still no key file in the sandbox.

Usage:
  python3 workspace/tools/secrets.py get <secret-name> [--project YOUR_PROJECT]
  python3 workspace/tools/secrets.py gcloud-token [--sa <service-account-email>]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.request

PROJECT = os.environ.get("SECRET_MANAGER_PROJECT", "__GCP_PROJECT__")
# SA whose token the CLI uses for deploys; runner identity needs tokenCreator on it.
# Override DEPLOY_SA to point at whatever deploy SA exists in the project.
DEPLOY_SA = os.environ.get("DEPLOY_SA", f"ai-ceo-runner@{PROJECT}.iam.gserviceaccount.com")


def _call(url: str, body: dict | None = None) -> dict:
    """HTTPS call routed through the sandbox egress proxy, which injects auth on the wire."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_secret(name: str, project: str = PROJECT) -> str:
    url = (f"https://secretmanager.googleapis.com/v1/projects/{project}"
           f"/secrets/{name}/versions/latest:access")
    return base64.b64decode(_call(url)["payload"]["data"]).decode("utf-8").strip()


def gcloud_token(sa: str = DEPLOY_SA) -> str:
    url = (f"https://iamcredentials.googleapis.com/v1/projects/-/"
           f"serviceAccounts/{sa}:generateAccessToken")
    return _call(url, {"scope": ["https://www.googleapis.com/auth/cloud-platform"]})["accessToken"]


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get"); g.add_argument("name"); g.add_argument("--project", default=PROJECT)
    t = sub.add_parser("gcloud-token"); t.add_argument("--sa", default=DEPLOY_SA)
    a = ap.parse_args()
    if a.cmd == "get":
        print(get_secret(a.name, a.project))
    elif a.cmd == "gcloud-token":
        print(gcloud_token(a.sa))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
