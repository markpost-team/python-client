"""E2E fixtures for the Markpost SDK tests.

These tests run against a real markpost container (see docker-compose.yml).
They are marked ``@pytest.mark.e2e`` and skipped unless the container is up.
"""

from __future__ import annotations

import os
import time

import pytest

from markpost import AsyncMarkpost, Markpost

# Default admin credentials seeded by the backend (config.go:247-248 +
# InitializeFirstAdmin at main.go:298).
ADMIN_USER = os.getenv("MARKPOST_E2E_USER", "markpost")
ADMIN_PASS = os.getenv("MARKPOST_E2E_PASS", "markpost")
BASE_URL = os.getenv("MARKPOST_E2E_URL", "http://localhost:2053")

# After a logout / token revocation the backend takes a moment to propagate the
# access-token blacklist across its instances. A small grace period keeps
# back-to-back auth-state-mutating tests from racing that propagation.
SETTLE_SECONDS = 0.5


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


def _is_container_up() -> bool:
    """Cheap liveness probe so the suite skips cleanly when no container runs."""
    import httpx

    try:
        r = httpx.get(f"{BASE_URL}/api/v1/health", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip e2e tests when the container isn't reachable."""
    if _is_container_up():
        return
    skip = pytest.mark.skip(reason="markpost e2e container is not up (start it via run.sh)")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)


def _force_password(desired: str) -> None:
    """Best-effort reset of the admin password to ``desired``.

    The whole suite runs against a single seeded admin user. Some tests change
    the password or rotate/revoke its tokens; if one fails mid-flight it could
    leave the user in an unknown state and poison the rest of the suite. We try
    logging in with the known candidates and reset to ``desired`` when needed.
    Silently no-ops if the container isn't reachable.
    """
    candidates = [desired, "new-e2e-pass-123", "newpass123", "tmp-e2e-pass-9"]
    for pw in candidates:
        try:
            with Markpost(BASE_URL, ADMIN_USER, pw) as c:
                if pw != desired:
                    c.change_password(pw, desired)
                return
        except Exception:
            continue


@pytest.fixture(autouse=True)
def _isolate_admin_identity():
    """Guarantee a known-good admin identity around every e2e test.

    Resets the password to the default before AND after each test and lets the
    backend settle, so token-blacklist / revocation propagation can't race the
    next test. This is necessary because all tests share one admin user.
    """
    _force_password(ADMIN_PASS)
    yield
    _force_password(ADMIN_PASS)
    time.sleep(SETTLE_SECONDS)


@pytest.fixture
def admin_client():
    """A logged-in sync admin client; closed when the test ends."""
    with Markpost(BASE_URL, ADMIN_USER, ADMIN_PASS) as client:
        yield client


@pytest.fixture
async def async_admin_client():
    """A logged-in async admin client; closed when the test ends.

    asyncio_mode=auto lets this be an ``async def`` fixture directly. Auto-login
    runs on ``__aenter__``.
    """
    async with AsyncMarkpost(BASE_URL, ADMIN_USER, ADMIN_PASS) as client:
        yield client
