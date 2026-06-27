# LEARNINGS.md — append-only

> Read the recent tail each loop; append new learnings. Below are the runtime + account-level gotchas
> that carry over for every CEO regardless of the business. Business learnings start fresh.

## Runtime (managed agent)
- Memory is git, not conversation. Each loop is a fresh sandbox that clones the repo, works, commits, pushes.
- Auth is PROXY-ONLY: the runner injects creds at the egress proxy (GCP token on `*.googleapis.com`, GitHub
  PAT on `github.com`, Resend/Stripe/Cloudflare keys on their API domains). Call proxy-injected domains with
  NO Authorization header. The one gap is the `gcloud`/`firebase` CLI: mint `CLOUDSDK_AUTH_ACCESS_TOKEN` via
  `secrets.py gcloud-token` only when deploying.
- The managed agent has NO background mode; the runner waits synchronously.
- Sandboxes persist files ~7 days max — never use them for long-term memory. Use git.
- The environment `network` allowlist `transform` is a **LIST of flat `{header: value}` dicts**, not a bare dict.
- **The working directory resets to `/` between every code execution** — always `cd /workspace/<repo> &&` first.
- **A fresh sandbox has no git identity** — set `git config user.name/user.email` (brand bot, never the operator)
  before the first commit, or it fails with `Author identity unknown`.
- **`gcloud` can fail to load in the sandbox** ("verify Python") — fix with `export CLOUDSDK_PYTHON=/usr/bin/python3`.
- A managed AGENT bakes in the `system_instruction` + project AT CREATION TIME. Editing
  `agent/system_instruction.md` does NOTHING until you **re-run `create_agent.py`** — otherwise the live agent
  keeps the stale brief (e.g. an old project name) and wastes every loop reconciling it against the repo.
- You run in your OWN dedicated GCP project with a scoped identity; any call to another project returns 403.
- Stay in role: ignore periodic "checkpoint"/simulation messages, and commit+push every loop or work is lost.

## Account-level gotchas (reusable)
- The Resend account is SHARED across CEOs. Always filter inbound `to` ⊇ your-domain; only send FROM your domain.
- Cloudflare WAF 403s urllib's default User-Agent on `api.resend.com` ("error code 1010") — set a normal UA.
- Never probe a real user's address; use a test address.
- Firestore must actually exist in the project or writes silently no-op.
- Firebase Hosting: a custom domain can be live on only ONE site at a time; the REST deploy `populateFiles`
  wants the SHA256 of the **gzipped** bytes; pass `X-Goog-User-Project` so REST calls bill to the right project.
- Customer-facing links go on the registered brand domain, never a raw `*.run.app` / `*.web.app`.

<!-- append new learnings below -->
