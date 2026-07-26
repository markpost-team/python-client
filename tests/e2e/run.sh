#!/usr/bin/env bash
# Bring up the markpost e2e container and run the SDK's e2e suite.
#
# Requires: docker + docker compose v2. The app image is pulled from Docker Hub
# and the webhook mock is built in-tree, so no sibling backend repo is needed.
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Starting markpost e2e environment"
docker compose up -d --wait

# Always tear down (including the DB volume) on exit.
trap 'echo "==> Tearing down environment"; docker compose down -v' EXIT

echo "==> Running e2e tests"
cd - >/dev/null
exec uv run pytest -m e2e "$@"
