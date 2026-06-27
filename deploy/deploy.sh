#!/usr/bin/env bash
# Provision the hourly trigger: build the container, deploy it to Cloud Run (private),
# and create a Cloud Scheduler job that hits it once an hour with an OIDC token.
#
# The Gemini managed agent does the real work; this is only the cron trigger.
#
# Prereqs: gcloud authenticated, the Gemini API key stored in Secret Manager as
# `gemini-api-key`, and the agent already created (python agent/create_agent.py).
#
# Usage:  cd <repo root> && bash deploy/deploy.sh
set -euo pipefail

# ---- config (override via env) ---------------------------------------------------------
PROJECT="${GCP_PROJECT:?set GCP_PROJECT to the dedicated CEO project}"
REGION="${GCP_REGION:-europe-west1}"
SERVICE="${SERVICE:-ai-ceo-trigger}"
AGENT_ID="${AGENT_ID:-ai-ceo}"
WORKSPACE_REPO_URL="${WORKSPACE_REPO_URL:-}"        # e.g. https://github.com/<you>/ai-company.git
SKILLS_REPO_URL="${SKILLS_REPO_URL:-https://github.com/SaschaHeyer/ceo-skills}"  # shared skills
SECRET_MANAGER_PROJECT="${SECRET_MANAGER_PROJECT:-$PROJECT}"
GEMINI_SECRET="${GEMINI_SECRET:-gemini-api-key}"     # SM secret holding the Gemini API key
GITHUB_PAT_SECRET="${GITHUB_PAT_SECRET:-github-pat}" # SM secret holding a GitHub PAT (for push)
SCHEDULE="${SCHEDULE:-0 * * * *}"                     # hourly, on the hour
ENABLE_SCHEDULE="${ENABLE_SCHEDULE:-0}"               # 0 = MANUAL mode (no Cloud Scheduler job)
RUNTIME_SA="${RUNTIME_SA:-ai-ceo-runner@${PROJECT}.iam.gserviceaccount.com}"
SCHED_SA="${SCHED_SA:-ai-ceo-scheduler@${PROJECT}.iam.gserviceaccount.com}"
# ---------------------------------------------------------------------------------------

echo "== Enabling APIs =="
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com firebasehosting.googleapis.com \
  --project "$PROJECT"

echo "== Service accounts =="
gcloud iam service-accounts create ai-ceo-runner --project "$PROJECT" \
  --display-name "Autonomous CEO Cloud Run runtime" 2>/dev/null || true
gcloud iam service-accounts create ai-ceo-scheduler --project "$PROJECT" \
  --display-name "Autonomous CEO Scheduler invoker" 2>/dev/null || true

# The runtime SA is the identity the *sandbox* acts as (its token is injected via the egress
# proxy). the target project is THIS CEO's DEDICATED project, so broad roles here are fine — the
# isolation that matters is that this SA has NOTHING on any other project (e.g. niche-ceo-4).
echo "== Granting runtime SA roles on $PROJECT (editor + firebase + secret access) =="
for ROLE in roles/editor roles/firebase.admin roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${RUNTIME_SA}" --role "$ROLE" --condition=None >/dev/null
done

echo "== Build + deploy to Cloud Run from source (uses ./Dockerfile) =="
gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --source . \
  --service-account "$RUNTIME_SA" \
  --no-allow-unauthenticated \
  --timeout 3600 --memory 512Mi --cpu 1 --max-instances 1 --concurrency 1 \
  --set-env-vars "AGENT_ID=${AGENT_ID},WORKSPACE_REPO_URL=${WORKSPACE_REPO_URL},SKILLS_REPO_URL=${SKILLS_REPO_URL},SECRET_MANAGER_PROJECT=${SECRET_MANAGER_PROJECT},GITHUB_PAT_SECRET=${GITHUB_PAT_SECRET}" \
  --set-secrets "GEMINI_API_KEY=${GEMINI_SECRET}:latest"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
echo "Service URL: $URL"

if [ "${ENABLE_SCHEDULE}" = "1" ]; then
  echo "== Let the scheduler SA invoke the service =="
  gcloud run services add-iam-policy-binding "$SERVICE" --project "$PROJECT" --region "$REGION" \
    --member "serviceAccount:${SCHED_SA}" --role roles/run.invoker

  echo "== Cloud Scheduler: trigger '$SCHEDULE' with OIDC (no retries, so a long loop can't double-fire) =="
  gcloud scheduler jobs create http ai-ceo-cron --project "$PROJECT" --location "$REGION" \
    --schedule "$SCHEDULE" --time-zone "Europe/Berlin" \
    --uri "$URL/" --http-method POST \
    --oidc-service-account-email "$SCHED_SA" --oidc-token-audience "$URL" \
    --attempt-deadline 1800s --max-retry-attempts 0 \
    2>/dev/null \
    || gcloud scheduler jobs update http ai-ceo-cron --project "$PROJECT" --location "$REGION" \
         --schedule "$SCHEDULE" --time-zone "Europe/Berlin" \
         --uri "$URL/" --http-method POST \
         --oidc-service-account-email "$SCHED_SA" --oidc-token-audience "$URL" \
         --attempt-deadline 1800s --max-retry-attempts 0
  echo
  echo "Done. The CEO runs on schedule '$SCHEDULE' (Europe/Berlin) on the managed runtime."
  echo "Run one loop now:  gcloud scheduler jobs run ai-ceo-cron --location $REGION --project $PROJECT"
else
  echo
  echo "== Schedule DISABLED (manual mode) — no Cloud Scheduler job created =="
  echo "Run a loop manually:"
  echo "  python3 runner/run_loop.py                     # locally"
  echo "  curl -X POST -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/   # via the deployed service"
  echo "Enable the hourly schedule later:  ENABLE_SCHEDULE=1 bash deploy/deploy.sh"
fi
echo "Tail logs:  gcloud run services logs read $SERVICE --region $REGION --project $PROJECT"
