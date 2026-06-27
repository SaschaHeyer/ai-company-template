# ai-company-template — spin up a new autonomous CEO

A reusable template for standing up an **autonomous AI CEO**: a Gemini managed agent that runs a real
business on its own, one loop at a time, with the operator in the loop only for money decisions. Clone
it per CEO, fill a few placeholders, and you have a fully isolated company running on a schedule.

Every CEO built from this template **operates the same way** — see **[STANDARDS.md](STANDARDS.md)**
(operator comms, email digests, inbound-email handling, CRM, Stripe, Resend, spend gate, git-as-memory).

## Architecture (same for every CEO)
- **Brief** = `agent/system_instruction.md` (baked into the managed agent). Runbook = `workspace/CEO.md` (read each loop).
- **Memory = git.** Each loop is a fresh sandbox that clones the repo, works, commits, pushes. No conversation memory.
- **Auth = proxy-only.** The runner ([runner/run_loop.py](runner/run_loop.py)) injects every credential at the
  egress proxy — Google APIs, GitHub, and Resend/Stripe/Cloudflare keys — so nothing lands in the sandbox.
- **Isolation.** Each CEO gets its **own GCP project** + a **scoped runner SA**, so it can't touch any other project.
- **Trigger.** Local `run_loop.py`, or Cloud Run + Cloud Scheduler ([deploy/deploy.sh](deploy/deploy.sh)) for unattended runs.

## Fast path: the `new-ceo` skill
If you have the **`new-ceo`** Claude Code skill installed, just run it and answer the prompts — it does
everything below (project, billing, secrets, scoped SA, repo, agent, first loop). That's the whole point.

## Manual setup (what the skill automates)
Per CEO, with an account that can create projects + link billing:

1. **GCP project + billing**
   ```bash
   gcloud projects create ai-ceo-N            # pick a unique id
   gcloud billing projects link ai-ceo-N --billing-account=XXXXXX-XXXXXX-XXXXXX
   gcloud services enable secretmanager.googleapis.com firestore.googleapis.com \
     firebasehosting.googleapis.com run.googleapis.com cloudbuild.googleapis.com --project=ai-ceo-N
   ```
2. **Secrets** (dedicated Stripe + Resend per CEO) into the project's Secret Manager:
   `gemini-api-key` (mint a Gemini key under THIS project — it sets the agent's runtime/billing),
   `resend-api-key`, `stripe-secret-key`, `stripe-publishable-key`, `cloudflare-api-token`, `github-pat`.
3. **Scoped runner SA** (hard isolation):
   ```bash
   gcloud iam service-accounts create ai-ceo-runner --project=ai-ceo-N
   for R in roles/editor roles/firebase.admin roles/secretmanager.secretAccessor; do
     gcloud projects add-iam-policy-binding ai-ceo-N \
       --member=serviceAccount:ai-ceo-runner@ai-ceo-N.iam.gserviceaccount.com --role=$R --condition=None; done
   gcloud iam service-accounts add-iam-policy-binding ai-ceo-runner@ai-ceo-N.iam.gserviceaccount.com \
     --member="user:YOU@example.com" --role=roles/iam.serviceAccountTokenCreator --project=ai-ceo-N
   ```
4. **The CEO's repo** (its git memory): create a private GitHub repo, push this template to it, and
   replace the `__PLACEHOLDERS__` (`__GCP_PROJECT__`, `__REPO_URL__`, `__OWNER_ACCOUNT__`) in
   `workspace/tools/*.py` and `.env`.
5. **Configure + run**
   ```bash
   cp .env.example .env && $EDITOR .env && source .env   # fill GCP_PROJECT / WORKSPACE_REPO_URL / GCLOUD_ACCOUNT
   python agent/create_agent.py                          # register the managed agent under this project's Gemini key
   python runner/run_loop.py                             # first loop (streams)
   ```
6. **Schedule (optional, unattended):** `ENABLE_SCHEDULE=1 SCHEDULE="0 */2 * * *" bash deploy/deploy.sh`

## The operator's side, once it's running
- The CEO **emails you a digest** each loop/day, and you steer it back by editing `workspace/human-tasks.md`
  (it reads that first every loop). Approve spend by writing **APPROVED** under the standing directive.
- The first loop will (if the business is undefined) **propose a business** and wait for your approval.

## Files
```
agent/        system_instruction.md (the brief) + create/delete/list_agents.py
runner/       run_loop.py (the trigger) + call_agent.py (ad-hoc chat)
deploy/       main.py + Dockerfile + deploy.sh (Cloud Run + Scheduler)
workspace/    CEO.md, human-tasks.md, loop_state.md, BUSINESS.md, LEARNINGS.md
              tools/: secrets.py (proxy auth), send_digest.py (operator email), crm.py (Firestore CRM)
STANDARDS.md  the shared operating model every CEO follows
```
