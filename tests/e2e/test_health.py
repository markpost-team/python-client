"""E2E: health check (TESTING §5.4.1)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


def test_health_returns_ok(admin_client):
    # admin_client just needs any reachable client; health is public.
    assert admin_client.health() == "ok"
