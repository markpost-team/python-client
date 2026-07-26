# Webhook mock for the Markpost SDK e2e suite.
#
# A self-contained reimplementation of the backend's webhook mock in plain
# Python, so `docker compose up` needs no checkout of the sibling backend repo.
# Built in-place by tests/e2e/docker-compose.yml.
FROM python:3.12-alpine

RUN apk add --no-cache curl

WORKDIR /app

COPY mock_server.py ./

# stdlib only — no dependencies to install.
EXPOSE 3002

# ThreadingHTTPServer handles concurrent deliveries + assertions safely.
CMD ["python", "mock_server.py"]
