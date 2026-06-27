# Cloud Run trigger container. Tiny on purpose: it only fires the hourly loop on the
# Gemini managed runtime, it does not run the business work itself.
FROM python:3.12-slim

WORKDIR /app

COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN pip install --no-cache-dir -r /app/deploy/requirements.txt

COPY agent/ /app/agent/
COPY runner/ /app/runner/
COPY deploy/ /app/deploy/

ENV PORT=8080
# 1 worker, long timeout: a single loop can run for many minutes on the managed runtime,
# and we wait synchronously for it (the antigravity agent does not support background=True).
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 3600 deploy.main:app
