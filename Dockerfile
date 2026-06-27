# Root Dockerfile so `gcloud run deploy --source .` builds the trigger from the repo root.
# Tiny on purpose: it only fires the hourly/2-hourly loop on the Gemini managed runtime.
FROM python:3.12-slim

WORKDIR /app

COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN pip install --no-cache-dir -r /app/deploy/requirements.txt

COPY agent/ /app/agent/
COPY runner/ /app/runner/
COPY deploy/ /app/deploy/

ENV PORT=8080
# 1 worker, long timeout: a loop runs for many minutes on the managed runtime and we wait
# synchronously (the antigravity agent has no background mode).
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 3600 deploy.main:app
