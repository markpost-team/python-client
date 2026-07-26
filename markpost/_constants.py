"""Default values shared across the sync and async clients.

All values here are backend-derived (see SPEC §9) or pure SDK policy.
"""

from __future__ import annotations

import httpx

# httpx has no default timeout and would hang forever; the SDK forces one.
# connect/read/write/pool tuned for a typical JSON API.
DEFAULT_TIMEOUT: httpx.Timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)

# Retry policy (SPEC §9.3): how many times to retry a transient failure.
DEFAULT_MAX_RETRIES = 2

# Exponential backoff parameters (SPEC §9.2).
RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 8.0

# When the access token has less than this many seconds left, the SDK
# proactively single-flight refreshes it before the request goes out.
TOKEN_REFRESH_MARGIN = 60.0

# All authenticated backend endpoints live under this prefix.
API_PREFIX = "/api/v1"
