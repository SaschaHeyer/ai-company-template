#!/usr/bin/env python3
"""send_digest.py — email the operator a digest via Resend (STANDARD operator-comms tool).

Every CEO uses this to send the operator a short digest each loop/day (what shipped, what's next,
anything needing a decision). Resend auth is injected by the egress proxy on `api.resend.com`, so we
send NO Authorization header. Set FROM_EMAIL to your own brand sender once your domain is verified.

Usage:
  FROM_EMAIL="Acme CEO <alerts@acme.com>" python3 send_digest.py <operator_email> <subject> <html_file>
"""
import json
import os
import sys
import urllib.error
import urllib.request

# Set this to your verified brand sender, e.g. "Acme CEO <alerts@acme.com>".
FROM_EMAIL = os.environ.get("FROM_EMAIL", "CEO <alerts@your-brand-domain.example>")


def send_digest(to_email: str, subject: str, html: str) -> bool:
    body = {"from": FROM_EMAIL, "to": [to_email], "subject": subject, "html": html}
    # Plain User-Agent so Cloudflare's WAF in front of Resend doesn't 403 (error 1010);
    # the egress proxy injects the Resend auth, so do NOT add an Authorization header.
    headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request("https://api.resend.com/emails",
                                 data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("digest sent:", json.load(r).get("id"))
            return True
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"Resend {e.code}: {e.read().decode('utf-8', 'replace')}\n")
        return False
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"send error: {e}\n")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: send_digest.py <operator_email> <subject> <html_file>", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[3], encoding="utf-8") as f:
        html_content = f.read()
    sys.exit(0 if send_digest(sys.argv[1], sys.argv[2], html_content) else 1)
