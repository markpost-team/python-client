"""Async client parity (TESTING §4.7).

Mirrors the most important scenarios from the sync suites against
``AsyncMarkpost``: lazy auto-login, single-flight refresh (async), 401
auto-refresh-retry-once, retry backoff via anyio, and an end-to-end
create→get→list→delete flow.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from markpost import (
    AsyncMarkpost,
    AuthenticationError,
)

from .conftest import BASE_URL, login_response, refresh_response


# E-AS1-style: full happy path on async client --------------------------------
@respx.mock
async def test_async_full_flow(logged_in_async_client):
    respx.post(f"{BASE_URL}/mpk-k").mock(return_value=httpx.Response(201, json={"id": "p-1"}))
    respx.get(f"{BASE_URL}/p-1").mock(return_value=httpx.Response(200, text="<h1>Hi</h1>"))
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": 1, "qid": "p-1", "title": "T", "created_at": "2026-01-01T00:00:00Z"}],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    respx.delete(f"{BASE_URL}/api/v1/posts/p-1").mock(return_value=httpx.Response(204))

    created = await logged_in_async_client.create_post("T", "B", post_key="mpk-k")
    assert created.id == "p-1"
    html = await logged_in_async_client.get_post("p-1")
    assert "<h1>" in html
    page = await logged_in_async_client.list_posts()
    assert page.items[0].qid == "p-1"
    assert await logged_in_async_client.delete_post("p-1") is None


# Auto-login is lazy: performed on __aenter__ ---------------------------------
@respx.mock
async def test_async_lazy_auto_login_on_aenter():
    respx.post(f"{BASE_URL}/api/v1/auth/login").mock(return_value=login_response())
    client = AsyncMarkpost(BASE_URL, "alice", "secret")
    # No login yet — construction is synchronous and does no I/O.
    assert client._access_token is None
    async with client as c:
        assert c._access_token == "tok-access"


# Auto-login is lazy: also fires on first authenticated call (no `async with`) -
@respx.mock
async def test_async_lazy_auto_login_on_first_call():
    respx.post(f"{BASE_URL}/api/v1/auth/login").mock(return_value=login_response())
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0})
    )
    client = AsyncMarkpost(BASE_URL, "alice", "secret")
    assert client._access_token is None
    page = await client.list_posts()
    assert page.total == 0
    assert client._access_token == "tok-access"


# Async single-flight: concurrent 401s -> exactly one refresh ------------------
async def test_async_single_flight_refresh_once():
    """Many concurrent reactive refreshes collapse into a single ``_do_refresh``.

    We mock ``_do_refresh`` so the coroutines genuinely overlap inside the
    async refresh critical section (a real respx transport would serialize
    requests, hiding the dedup). This is the async analogue of the thread test
    in ``test_auth.py`` and guards SPEC risk R3.
    """
    import asyncio as _asyncio

    from markpost._models import RefreshTokenResult

    client = AsyncMarkpost(BASE_URL)
    client._access_token = "tok-access"
    client._refresh_token = "tok-refresh"

    refresh_calls = 0
    started = _asyncio.Event()

    async def fake_do_refresh():
        nonlocal refresh_calls
        started.set()
        # Yield so other coroutines pile up behind the asyncio.Lock.
        await _asyncio.sleep(0.05)
        refresh_calls += 1
        result = RefreshTokenResult(token="tok-access-2", refresh_token="tok-refresh-2", expires_in=3600)
        client._store_refresh(result)
        return result

    client._do_refresh = fake_do_refresh  # type: ignore[method-assign]

    results = await _asyncio.gather(*(client._force_refresh(stale_generation=0) for _ in range(10)))
    assert all(results)  # every caller observed a successful refresh
    assert refresh_calls == 1  # exactly one underlying refresh
    assert client._access_token == "tok-access-2"


# Async 401 auto-refresh retries once, then success ---------------------------
@respx.mock
async def test_async_401_auto_refresh_retries_once(logged_in_async_client):
    refresh = respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(return_value=refresh_response())
    posts = respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.Response(401, json={"code": "unauthorized", "message": "expired"}),
            httpx.Response(200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}),
        ]
    )
    result = await logged_in_async_client.list_posts()
    assert result.total == 0
    assert refresh.call_count == 1
    assert posts.call_count == 2


# Async retry sleep uses anyio (monkeypatched) --------------------------------
@respx.mock
async def test_async_retry_uses_anyio_sleep(logged_in_async_client, monkeypatch):
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("markpost._async.anyio.sleep", fake_sleep)
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.ConnectTimeout("down"),
            httpx.Response(200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}),
        ]
    )
    await logged_in_async_client.list_posts()
    assert len(slept) == 1
    assert slept[0] > 0


# Async proactive refresh before a request with near-expiry token -------------
@respx.mock
async def test_async_proactive_refresh(logged_in_async_client):
    logged_in_async_client._token_expires_at = 0.0  # always "expiring"
    refresh = respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(return_value=refresh_response())
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0})
    )
    await logged_in_async_client.list_posts()
    assert refresh.call_count == 1


# Async refresh with no refresh token raises ----------------------------------
async def test_async_refresh_without_token_raises():
    client = AsyncMarkpost(BASE_URL)
    with pytest.raises(AuthenticationError):
        await client.refresh_token()


# ---------------------------------------------------------------------------
# Async parity: mirror the remaining sync scenarios (TESTING §4.7).
# ---------------------------------------------------------------------------

CHANNEL_BODY = {
    "id": 1,
    "kind": "feishu",
    "name": "ops",
    "enabled": True,
    "configuration": {"webhook_url": "https://hook"},
    "keywords": "",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
}


@respx.mock
async def test_async_get_post_html_and_raw(logged_in_async_client):
    respx.get(f"{BASE_URL}/p-a").mock(return_value=httpx.Response(200, text="<h1>x</h1>"))
    html = await logged_in_async_client.get_post("p-a")
    assert "<h1>" in html


@respx.mock
async def test_async_get_post_304(logged_in_async_client):
    respx.get(f"{BASE_URL}/p-a").mock(return_value=httpx.Response(304))
    result = await logged_in_async_client.get_post("p-a", if_none_match='"e"')
    assert result is None


@respx.mock
async def test_async_get_post_key(logged_in_async_client):
    respx.get(f"{BASE_URL}/api/v1/post-key").mock(
        return_value=httpx.Response(200, json={"post_key": "mpk-z", "created_at": "2026-01-01T00:00:00Z"})
    )
    key = await logged_in_async_client.get_post_key()
    assert key == "mpk-z"
    assert logged_in_async_client._post_key == "mpk-z"


@respx.mock
async def test_async_change_password(logged_in_async_client):
    respx.post(f"{BASE_URL}/api/v1/auth/change-password").mock(
        return_value=httpx.Response(200, json={"message": "done"})
    )
    msg = await logged_in_async_client.change_password("old", "newpass123")
    assert msg == "done"


@respx.mock
async def test_async_logout_clears_tokens(logged_in_async_client):
    respx.post(f"{BASE_URL}/api/v1/auth/logout").mock(return_value=httpx.Response(200, json={"message": "bye"}))
    assert await logged_in_async_client.logout() is None
    assert logged_in_async_client._access_token is None


@respx.mock
async def test_async_health():
    respx.get(f"{BASE_URL}/api/v1/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    client = AsyncMarkpost(BASE_URL)
    assert await client.health() == "ok"


@respx.mock
async def test_async_list_channels(logged_in_async_client):
    respx.get(f"{BASE_URL}/api/v1/delivery/channels").mock(
        return_value=httpx.Response(200, json={"items": [CHANNEL_BODY]})
    )
    result = await logged_in_async_client.list_channels()
    assert len(result) == 1
    assert result[0].kind == "feishu"


@respx.mock
async def test_async_create_update_delete_channel(logged_in_async_client):
    respx.post(f"{BASE_URL}/api/v1/delivery/channels").mock(
        return_value=httpx.Response(201, json={"channel": CHANNEL_BODY})
    )
    respx.patch(f"{BASE_URL}/api/v1/delivery/channels/1").mock(
        return_value=httpx.Response(200, json={"channel": {**CHANNEL_BODY, "enabled": False}})
    )
    respx.delete(f"{BASE_URL}/api/v1/delivery/channels/1").mock(return_value=httpx.Response(204))
    ch = await logged_in_async_client.create_channel("feishu", "ops", {"webhook_url": "x"})
    assert ch.id == 1
    updated = await logged_in_async_client.update_channel(1, enabled=False)
    assert updated.enabled is False
    assert await logged_in_async_client.delete_channel(1) is None


@respx.mock
async def test_async_list_delivery_history(logged_in_async_client):
    respx.get(f"{BASE_URL}/api/v1/delivery/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "status": "delivered",
                        "last_error": "",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    page = await logged_in_async_client.list_delivery_history(channel_id=1)
    assert page.items[0].status == "delivered"


@respx.mock
async def test_async_admin_methods(logged_in_async_client):
    respx.get(f"{BASE_URL}/api/v1/admin/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "username": "u",
                        "email": "e",
                        "role": "admin",
                        "is_active": True,
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    respx.get(f"{BASE_URL}/api/v1/admin/posts").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "qid": "p-a",
                        "title": "t",
                        "user_id": 1,
                        "username": "u",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    respx.get(f"{BASE_URL}/api/v1/admin/delivery/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "name": "n",
                        "kind": "feishu",
                        "enabled": True,
                        "user_id": 1,
                        "configuration": {},
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    respx.get(f"{BASE_URL}/api/v1/admin/delivery/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "status": "delivered",
                        "last_error": "",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    respx.delete(f"{BASE_URL}/api/v1/admin/posts/p-a").mock(return_value=httpx.Response(204))

    users = await logged_in_async_client.admin_list_users()
    assert users.items[0].role == "admin"
    posts = await logged_in_async_client.admin_list_posts(search="t")
    assert posts.items[0].qid == "p-a"
    chans = await logged_in_async_client.admin_list_channels()
    assert chans.items[0].user_id == 1
    hist = await logged_in_async_client.admin_list_delivery_history()
    assert hist.items[0].status == "delivered"
    assert await logged_in_async_client.admin_delete_post("p-a") is None


@respx.mock
async def test_async_delete_post(logged_in_async_client):
    respx.delete(f"{BASE_URL}/api/v1/posts/p-a").mock(return_value=httpx.Response(204))
    assert await logged_in_async_client.delete_post("p-a") is None


@respx.mock
async def test_async_create_post_auto_fetch_key(logged_in_async_client):
    respx.get(f"{BASE_URL}/api/v1/post-key").mock(
        return_value=httpx.Response(200, json={"post_key": "mpk-f", "created_at": "2026-01-01T00:00:00Z"})
    )
    respx.post(f"{BASE_URL}/mpk-f").mock(return_value=httpx.Response(201, json={"id": "p-1"}))
    result = await logged_in_async_client.create_post("T", "B")
    assert result.id == "p-1"
