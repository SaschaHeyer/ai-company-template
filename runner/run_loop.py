#!/usr/bin/env python3
"""Fire ONE hourly CEO loop on the Gemini managed-agent runtime.

This is the managed-agent equivalent of one `claude` invocation in the old local setup.
It does NOT do any business work itself — it just triggers the agent. All the real work
(prospecting, redesigns, outreach, deploys) runs on Google's managed runtime inside the
sandbox, exactly as the brief in agent/system_instruction.md + workspace/CEO.md describes.

What this runner does each loop (PROXY-ONLY auth — no credential lands in the sandbox):
  1. Mint a short-lived GCP access token from the runner's own credentials (the Cloud Run
     runtime service account; locally your ADC). The proxy injects it on `*.googleapis.com`
     so the sandbox can reach Google APIs, and the runner uses it to read the third-party
     keys below.
  2. Resolve a GitHub PAT (env or Secret Manager) and read the Resend/Stripe/Cloudflare keys
     from Secret Manager.
  3. Build a per-loop `environment` config that (a) clones the workspace + skills repos and
     (b) injects ALL credentials (GCP token, GitHub PAT, the three API keys) via the network
     allowlist `transform` — the egress proxy adds them on the wire, never inside the sandbox.
  4. Call client.interactions.create(...) and wait for the loop to finish.

Memory model: identical to the old CEO. State lives in git, not in conversation history.
Each loop is a FRESH interaction + FRESH sandbox that clones the latest repo, reads the
state files, works, commits, and pushes. We intentionally do NOT chain previous_interaction_id
across hourly loops (that would grow context unboundedly); the repo IS the memory.

Requires: google-genai >= 2.3.0, google-auth
Docs: https://ai.google.dev/gemini-api/docs/managed-agents-quickstart.md.txt
      https://ai.google.dev/gemini-api/docs/agent-environment.md.txt
"""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import urllib.request

from google import genai

AGENT_ID = os.environ.get("AGENT_ID", "ai-ceo")
# Defaults to the agent's git-memory repo. Set WORKSPACE_REPO_URL="" to force smoke mode.
WORKSPACE_REPO_URL = os.environ.get(
    "WORKSPACE_REPO_URL", ""
).strip()
WORKSPACE_TARGET = os.environ.get("WORKSPACE_TARGET", "/workspace/repo")
SM_PROJECT = os.environ.get("SECRET_MANAGER_PROJECT", "")
GITHUB_PAT_SECRET = os.environ.get("GITHUB_PAT_SECRET", "")  # name of the SM secret, optional
# Shared skills library — the same repo the old CEO cloned at ./ceo-skills. Mounted as a
# second source each loop so the agent can read every SKILL.md (and push new skills it builds,
# since it's a separate repo). Set empty to skip.
SKILLS_REPO_URL = os.environ.get(
    "SKILLS_REPO_URL", "https://github.com/SaschaHeyer/ceo-skills"
).strip()
SKILLS_TARGET = os.environ.get("SKILLS_TARGET", "/workspace/ceo-skills")
STREAM = os.environ.get("LOOP_STREAM", "0") == "1"

# Third-party API keys injected at the egress proxy so they NEVER enter the sandbox.
# The runner fetches each from Secret Manager and the proxy adds the header on the wire.
# (secret name in Secret Manager, domain, header name, value template)
PROXY_API_KEYS = [
    ("resend-api-key",       "api.resend.com",     "Authorization", "Bearer {}"),
    ("stripe-secret-key",    "api.stripe.com",      "Authorization", "Bearer {}"),
    ("cloudflare-api-token", "api.cloudflare.com",  "Authorization", "Bearer {}"),
]

LOOP_PROMPT = (
    "Begin a new hourly loop. You are an OPERATOR, not a report writer: you work by EDITING FILES in "
    f"the git repo at {WORKSPACE_TARGET} and PUSHING them. Skills are at {SKILLS_TARGET}. "
    f"Read {WORKSPACE_TARGET}/workspace/CEO.md and follow it: authenticate (Step 0), read state + "
    "human-tasks + the recent LEARNINGS tail, pick the single highest-EV concrete task, and do it for "
    "real by WRITING FILES into the repo (notes, plans, code, drafts — whatever the task produces). "
    "CRITICAL: do NOT answer with a written report. Your deliverable is a pushed commit. Commit as you "
    f"go, and your FINAL action MUST be `cd {WORKSPACE_TARGET} && git add -A && git commit -m '...' && "
    "git push`, then `git log origin/main -1` to confirm it landed. If you have not pushed, you have "
    "done nothing. Only after pushing, end with ONE short line on what you shipped."
)

SMOKE_PROMPT = (
    "Smoke test (no workspace mounted). Confirm your runtime works: print the OS, python, "
    "node and gcloud versions, run `echo $(( 6 * 7 ))`, and confirm you can reach Google "
    "Search. Then state in one sentence that you are the autonomous CEO agent and ready to "
    "run hourly loops once a workspace repo is configured."
)


def mint_gcp_token() -> str | None:
    """Short-lived OAuth token for the runner's GCP identity.

    On Cloud Run this is the runtime SA via ADC. For LOCAL runs, set GCLOUD_ACCOUNT to a gcloud
    account that can reach the project, and set IMPERSONATE_SA to a service account so we mint a
    token SCOPED TO THAT SA ONLY (hard isolation — the sandbox then can't reach the owner's other
    projects, e.g. niche-ceo-4).
    """
    acct = os.environ.get("GCLOUD_ACCOUNT", "").strip()
    impersonate = os.environ.get("IMPERSONATE_SA", "").strip()
    if acct:
        try:
            cmd = ["gcloud", "auth", "print-access-token", "--account", acct]
            if impersonate:
                cmd += ["--impersonate-service-account", impersonate]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            tok = out.stdout.strip()
            if tok:
                return tok
            print(f"WARN: gcloud token for {acct} failed: {out.stderr.strip()[:200]}",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: gcloud token for {acct} errored: {e}", file=sys.stderr)
    try:
        import google.auth
        import google.auth.transport.requests

        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception as e:  # noqa: BLE001
        print(f"WARN: could not mint a GCP token ({e}). "
              "Google API auth + proxy-injected secrets will be unavailable this loop.",
              file=sys.stderr)
        return None


def _to_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                pass
    return dict(getattr(obj, "__dict__", {}) or {})


def fetch_secret_rest(name: str, project: str, token: str) -> str | None:
    """Read a Secret Manager secret value over REST using the runner's token."""
    url = (f"https://secretmanager.googleapis.com/v1/projects/{project}"
           f"/secrets/{name}/versions/latest:access")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)["payload"]["data"]
        return base64.b64decode(payload).decode("utf-8").strip()
    except Exception as e:  # noqa: BLE001
        print(f"WARN: could not read secret '{name}': {e}", file=sys.stderr)
        return None


def resolve_github_pat(token: str | None) -> str | None:
    pat = os.environ.get("GITHUB_PAT", "").strip()
    if pat:
        return pat
    if GITHUB_PAT_SECRET and token:
        return fetch_secret_rest(GITHUB_PAT_SECRET, SM_PROJECT, token)
    return None


def build_environment(gcp_token: str | None, gh_pat: str | None) -> dict | str:
    """Per-loop sandbox config: mount the workspace repo + inject credentials."""
    if not WORKSPACE_REPO_URL:
        return "remote"  # smoke mode: fresh sandbox, no git memory

    allowlist: list[dict] = []
    # NOTE: `transform` is a LIST of flat {header: value} dicts (SDK schema), not a bare dict.
    if gcp_token:
        # Egress proxy injects this on every *.googleapis.com call → the sandbox can read
        # Secret Manager / Firestore / Cloud APIs as the runner identity, no key file inside.
        bearer = [{"Authorization": f"Bearer {gcp_token}"}]
        allowlist += [
            {"domain": "googleapis.com", "transform": bearer},
            {"domain": "*.googleapis.com", "transform": bearer},
        ]
    if gh_pat:
        gh_basic = base64.b64encode(f"x-oauth-basic:{gh_pat}".encode()).decode()
        basic = [{"Authorization": f"Basic {gh_basic}"}]
        allowlist += [
            {"domain": "github.com", "transform": basic},
            {"domain": "*.github.com", "transform": basic},
        ]
    # Third-party API keys: fetched by the runner, injected by the proxy → never in the sandbox.
    # In-sandbox callers must hit these domains WITHOUT adding their own Authorization header.
    if gcp_token:
        for secret_name, domain, header, tmpl in PROXY_API_KEYS:
            value = fetch_secret_rest(secret_name, SM_PROJECT, gcp_token)
            if value:
                allowlist.append({"domain": domain, "transform": [{header: tmpl.format(value)}]})
                print(f"  proxy-auth: {domain} <- {secret_name}", file=sys.stderr)
    allowlist.append({"domain": "*"})  # everything else (pypi, npm, prospect sites, …)

    # Mount the workspace (git memory) and the shared skills library as separate repos.
    sources = [
        {"type": "repository", "source": WORKSPACE_REPO_URL, "target": WORKSPACE_TARGET},
    ]
    if SKILLS_REPO_URL:
        sources.append(
            {"type": "repository", "source": SKILLS_REPO_URL, "target": SKILLS_TARGET}
        )

    return {
        "type": "remote",
        "sources": sources,
        "network": {"allowlist": allowlist},
    }


def _remote_main_sha(repo_url: str, pat: str | None) -> str | None:
    """Current SHA of the repo's main branch via git ls-remote (PAT embedded for private repos)."""
    if not repo_url or not pat:
        return None
    authed = repo_url.replace("https://", f"https://x-oauth-basic:{pat}@", 1)
    try:
        out = subprocess.run(
            ["git", "ls-remote", authed, "refs/heads/main"],
            capture_output=True, text=True, timeout=30,
        )
        parts = out.stdout.split()
        return parts[0] if parts else None
    except Exception:  # noqa: BLE001
        return None


def _append_yaml(path: str, rec: dict) -> None:
    """Append one run as a YAML list item so the file stays a valid YAML sequence — load it later for
    charts with `import yaml; runs = yaml.safe_load(open(path))` (a list of dicts). No PyYAML needed to
    WRITE: the records are flat str/int/bool, so we format them by hand."""
    def fmt(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    keys = list(rec)
    block = [f"- {keys[0]}: {fmt(rec[keys[0]])}"] + [f"  {k}: {fmt(rec[k])}" for k in keys[1:]]
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("# per-loop cost log — a YAML sequence. Load with yaml.safe_load(open(this_file)).\n")
        f.write("\n".join(block) + "\n")


def _log_usage(ix, before_sha=None, after_sha=None, steps=None) -> None:
    """Report this loop's token consumption from the interaction's `usage` (the API returns it).

    Each loop is exactly ONE interaction, so `usage` IS the whole loop's cost. Prints a breakdown and,
    if COST_LOG is set, appends a YAML record to build per-loop history (for later charting). A euro
    estimate is added only when GEMINI_INPUT_RATE / GEMINI_OUTPUT_RATE (per 1M tokens) are set — otherwise
    we report exact tokens and leave the euro figure to the billing dashboard (antigravity is tiered).
    """
    usage_obj = getattr(ix, "usage", None) if ix is not None else None
    if usage_obj is None:
        print("\n💸 usage: (none returned)", flush=True)
        return
    u = _to_dict(usage_obj) or {}

    def g(k):
        v = u.get(k)
        if v is None:
            v = getattr(usage_obj, k, 0)
        return int(v or 0)

    inp, out, thought = g("total_input_tokens"), g("total_output_tokens"), g("total_thought_tokens")
    tool, cached, total = g("total_tool_use_tokens"), g("total_cached_tokens"), g("total_tokens")
    pushed = bool(before_sha and after_sha and after_sha != before_sha)
    line = (f"tokens total={total:,}  in={inp:,} out={out:,} thought={thought:,} "
            f"tool={tool:,} cached={cached:,}  steps={steps}  pushed={pushed}")
    ri = float(os.environ.get("GEMINI_INPUT_RATE", "0") or 0)
    ro = float(os.environ.get("GEMINI_OUTPUT_RATE", "0") or 0)
    cf = float(os.environ.get("GEMINI_CACHED_FACTOR", "0.1") or 0.1)   # gemini-3.5-flash cached read ≈ 0.1x input
    uncached = max(inp - cached, 0)
    est = (round(uncached / 1e6 * ri + cached / 1e6 * ri * cf + (out + thought + tool) / 1e6 * ro, 4)
           if (ri or ro) else None)
    if est is not None:
        line += f"  est~{est}"
    print(f"\n💸 {line}", flush=True)

    path = os.environ.get("COST_LOG", "").strip()
    if path:
        import datetime as _dt
        rec = {
            "ts": _dt.datetime.utcnow().isoformat(timespec="seconds"),
            "interaction_id": getattr(ix, "id", "") or "",
            "status": str(getattr(ix, "status", "") or ""),
            "total_tokens": total, "input_tokens": inp, "output_tokens": out,
            "thought_tokens": thought, "tool_tokens": tool, "cached_tokens": cached,
            "pushed": pushed, "steps": (steps if steps is not None else 0), "after_sha": (after_sha or "")[:12],
        }
        if est is not None:
            rec["est_cost"] = est
        _append_yaml(path, rec)
        print(f"   (logged to {path})", flush=True)


def main() -> int:
    if not os.environ.get("GEMINI_API_KEY"):
        print("ERROR: set GEMINI_API_KEY", file=sys.stderr)
        return 1

    gcp_token = mint_gcp_token()
    gh_pat = resolve_github_pat(gcp_token)
    environment = build_environment(gcp_token, gh_pat)
    prompt = LOOP_PROMPT if WORKSPACE_REPO_URL else SMOKE_PROMPT

    mode = "smoke (no workspace)" if not WORKSPACE_REPO_URL else f"loop on {WORKSPACE_REPO_URL}"
    print(f"== autonomous CEO :: firing {mode} ==")
    if not WORKSPACE_REPO_URL:
        print("   (smoke: set WORKSPACE_REPO_URL for a REAL loop — see README)", file=sys.stderr)
    elif not gcp_token:
        print("   WARN: no GCP token — set GCLOUD_ACCOUNT (local) so secrets/clone work",
              file=sys.stderr)

    client = genai.Client()
    before_sha = _remote_main_sha(WORKSPACE_REPO_URL, gh_pat)
    result_ix = None
    step_count = 0

    if STREAM:
        env_id = None
        _cancel = {"id": None}

        def _on_sigint(_sig, _frame):
            # Ctrl-C must cancel the SERVER-SIDE run, not just the local stream (else it keeps billing).
            iid = _cancel["id"]
            print(f"\n\n^C — cancelling server-side interaction {iid or '(none captured yet)'}…", flush=True)
            if iid:
                try:
                    client.interactions.cancel(id=iid)
                    print(f"cancelled {iid}.", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"cancel call failed: {e}\n  retry: python3 runner/cancel_loop.py {iid}", file=sys.stderr)
            raise SystemExit(130)

        signal.signal(signal.SIGINT, _on_sigint)
        stream = client.interactions.create(
            agent=AGENT_ID, input=prompt, environment=environment, stream=True,
        )
        for event in stream:
            et = getattr(event, "event_type", "") or getattr(event, "type", "")
            if et == "interaction.created":
                _ix = getattr(event, "interaction", None)
                env_id = getattr(_ix, "environment_id", None)
                _cancel["id"] = getattr(_ix, "id", None)
                print(f"[interaction {_cancel['id']} | sandbox {env_id}]", flush=True)
                print(f"  cancel: Ctrl-C here, or  python3 runner/cancel_loop.py {_cancel['id']}\n", flush=True)
            elif et == "step.start":
                step_count += 1
                sd = _to_dict(getattr(event, "step", None))
                stype = sd.get("type") or "step"
                if stype == "thought":
                    print("\n🧠 ", end="", flush=True)
                elif stype == "model_output":
                    print("\n💬 ", end="", flush=True)
                elif stype == "function_call":
                    print(f"\n▶ {sd.get('name') or 'call'}", flush=True)
                elif stype == "code_execution_call":
                    print("\n▶ code", flush=True)
            elif et == "step.delta":
                dd = _to_dict(getattr(event, "delta", None))
                dtype = dd.get("type")
                if dtype in ("text", "thought_summary"):
                    # text may arrive as delta.content.text, delta.content[].text, or delta.text directly
                    content = dd.get("content")
                    txt = ""
                    if isinstance(content, dict):
                        txt = content.get("text") or ""
                    elif isinstance(content, list):
                        txt = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                    txt = txt or dd.get("text") or ""
                    if txt:
                        print(txt, end="", flush=True)            # reasoning (thought_summary) + the reply (text)
                elif dtype == "code_execution_call":
                    code = (dd.get("arguments") or {}).get("code")
                    if code:
                        print(f"\n  $ {code}", flush=True)       # the command it runs
                elif dtype == "code_execution_result":
                    res = dd.get("result")
                    rt = res if isinstance(res, str) else ""
                    if not rt and res:
                        d = _to_dict(res)
                        rt = d.get("output", "") if isinstance(d, dict) else ""
                        if isinstance(rt, dict):
                            rt = rt.get("string_value") or rt.get("stringValue") or ""
                    print(f"\n  → {str(rt)[:500]}" if rt else "\n  → (ok, no output)", flush=True)
                elif os.environ.get("LOOP_RAW"):
                    print(f"\n  [delta {dtype}: {str(dd)[:300]}]", flush=True)  # LOOP_RAW=1 surfaces any unhandled delta
            elif et == "interaction.completed":
                ix = getattr(event, "interaction", None)
                result_ix = ix
                print(f"\n\n-- done. status={getattr(ix, 'status', '?')} env={env_id}", flush=True)
    else:
        interaction = client.interactions.create(
            agent=AGENT_ID, input=prompt, environment=environment,
        )
        print(f"status: {getattr(interaction, 'status', '?')}")
        print(f"interaction_id: {getattr(interaction, 'id', '?')}")
        print(f"environment_id: {getattr(interaction, 'environment_id', '?')}")
        print("\n--- CEO loop summary ---\n")
        print(getattr(interaction, "output_text", "") or "(no text output)")
        result_ix = interaction

    # Did the loop actually persist its work? Git-as-memory only works if it pushed.
    after_sha = _remote_main_sha(WORKSPACE_REPO_URL, gh_pat)
    if before_sha and after_sha == before_sha:
        print("\nWARN: the loop pushed NO commit — its work was NOT persisted to git. "
              "The agent must commit + push every loop.", file=sys.stderr)
    elif before_sha and after_sha and after_sha != before_sha:
        print(f"\n[git: pushed {before_sha[:7]} -> {after_sha[:7]}]", file=sys.stderr)

    _log_usage(result_ix, before_sha, after_sha, step_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
