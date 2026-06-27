#!/usr/bin/env python3
"""crm.py — minimal Firestore CRM (STANDARD customer store) over the proxy-injected REST API.

One Firestore collection (`customers`), one document per person. Auth is injected by the egress proxy
on `*.googleapis.com`, so no token handling here — we just pass `X-Goog-User-Project`. Extend the field
set per business; keep `email` + `status` + `created`.

Usage:
  python3 crm.py add <email> [--status active] [--field k=v ...]
  python3 crm.py list
  python3 crm.py set <email> --status <status> [--field k=v ...]
  python3 crm.py export        # write a git-tracked mirror to crm/customers.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import urllib.request

PROJECT = os.environ.get("GCP_PROJECT", "__GCP_PROJECT__")
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
H = {"X-Goog-User-Project": PROJECT, "Content-Type": "application/json"}


def _req(url: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=H, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _to_fields(d: dict) -> dict:
    return {k: {"stringValue": str(v)} for k, v in d.items()}


def _from_fields(doc: dict) -> dict:
    out = {"id": doc["name"].split("/")[-1]}
    for k, v in (doc.get("fields") or {}).items():
        out[k] = next(iter(v.values()))
    return out


def _doc_id(email: str) -> str:
    return email.replace("@", "_at_").replace(".", "_").lower()


def add_or_set(email: str, status: str, extra: dict) -> None:
    fields = {"email": email, "status": status, **extra}
    _req(f"{BASE}/customers/{_doc_id(email)}", "PATCH", {"fields": _to_fields(fields)})
    print(f"saved customer {email} [{status}]")
    export()


def list_customers() -> list[dict]:
    docs = _req(f"{BASE}/customers").get("documents", [])
    return [_from_fields(d) for d in docs]


def export() -> None:
    rows = list_customers()
    out = pathlib.Path("crm"); out.mkdir(exist_ok=True)
    (out / "customers.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"exported {len(rows)} customers -> crm/customers.json")


def _parse_fields(items: list[str]) -> dict:
    return dict(kv.split("=", 1) for kv in (items or []))


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("email"); a.add_argument("--status", default="active"); a.add_argument("--field", action="append")
    s = sub.add_parser("set"); s.add_argument("email"); s.add_argument("--status", required=True); s.add_argument("--field", action="append")
    sub.add_parser("list"); sub.add_parser("export")
    args = ap.parse_args()
    if args.cmd in ("add", "set"):
        add_or_set(args.email, args.status, _parse_fields(args.field))
    elif args.cmd == "list":
        for c in list_customers():
            print(c)
    elif args.cmd == "export":
        export()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
