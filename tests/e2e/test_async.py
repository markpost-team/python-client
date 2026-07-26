"""E2E: async client end-to-end (TESTING §5.4.7)."""

from __future__ import annotations

import pytest

from markpost import AsyncMarkpost

pytestmark = pytest.mark.e2e


# E-AS1: async full lifecycle -------------------------------------------------
async def test_async_full_lifecycle(base_url):
    async with AsyncMarkpost(base_url, "markpost", "markpost") as client:
        created = await client.create_post("async e2e", "# body")
        qid = created.id
        try:
            assert qid.startswith("p-")
            html = await client.get_post(qid)
            assert isinstance(html, str)
            page = await client.list_posts(limit=100)
            assert qid in {item.qid for item in page.items}
        finally:
            await client.delete_post(qid)


# E-AS2: concurrent refresh collapses to one backend call ---------------------
async def test_async_single_flight_real(base_url):
    """Concurrent expiry-triggered refreshes must hit /auth/refresh once.

    We observe this indirectly: with a near-expiry token, many concurrent
    requests must all succeed (no 401 storm) and the session must survive (no
    reuse-detection nuking). If single-flight were broken, reuse detection would
    revoke all tokens and the requests would fail.
    """
    import asyncio

    async with AsyncMarkpost(base_url, "markpost", "markpost") as client:
        # Force the proactive-refresh path on every call.
        client._token_expires_at = 0.0
        results = await asyncio.gather(*(client.health() for _ in range(8)), return_exceptions=True)
        assert all(r == "ok" for r in results), f"unexpected failures: {results}"
