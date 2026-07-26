"""Auth flows (TESTING §4.2). Sync variants; async equivalents live in
``test_async.py``.

Covers login, refresh, single-flight refresh, 401 auto-refresh-retry-once,
logout token clearing, change_password, get_post_key.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
import respx

from markpost import (
    AuthenticationError,
    BadRequestError,
    Markpost,
    UnprocessableEntityError,
)

from .conftest import BASE_URL, login_response, refresh_response


# U-A1: login success stores token --------------------------------------------
@respx.mock
def test_login_success_stores_token():
    login = respx.post(f"{BASE_URL}/api/v1/auth/login").mock(return_value=login_response())
    client = Markpost(BASE_URL)
    result = client.login("alice", "secret")

    assert login.called
    assert result.token == "tok-access"
    assert result.refresh_token == "tok-refresh"
    # Internal state: token stored, expiry computed.
    assert client._access_token == "tok-access"
    assert client._refresh_token == "tok-refresh"
    assert client._token_expires_at > 0
    # login uses auth="none" -> request must NOT carry an Authorization header.
    sent_req = login.calls.last.request
    assert "authorization" not in {k.lower() for k in sent_req.headers}


# U-A2: login 401 --------------------------------------------------------------
@respx.mock
def test_login_invalid_credentials():
    respx.post(f"{BASE_URL}/api/v1/auth/login").mock(
        return_value=httpx.Response(401, json={"code": "invalid_credentials", "message": "bad"})
    )
    client = Markpost(BASE_URL)
    with pytest.raises(AuthenticationError) as exc_info:
        client.login("alice", "wrong")
    assert exc_info.value.code == "invalid_credentials"
    assert exc_info.value.status_code == 401


# U-A3: login 400 --------------------------------------------------------------
@respx.mock
def test_login_bad_request():
    respx.post(f"{BASE_URL}/api/v1/auth/login").mock(
        return_value=httpx.Response(400, json={"code": "invalid_request", "message": "missing"})
    )
    client = Markpost(BASE_URL)
    with pytest.raises(BadRequestError):
        client.login("", "")


# U-A4: refresh success rotates tokens ----------------------------------------
@respx.mock
def test_refresh_success_rotates_tokens(logged_in_client):
    route = respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(return_value=refresh_response())
    result = logged_in_client.refresh_token()
    assert route.called
    assert result.token == "tok-access-2"
    assert result.refresh_token == "tok-refresh-2"
    # New pair overwrites the old.
    assert logged_in_client._access_token == "tok-access-2"
    assert logged_in_client._refresh_token == "tok-refresh-2"
    # Body carried the OLD refresh token.
    sent = route.calls.last.request
    assert json.loads(sent.content) == {"refresh_token": "tok-refresh"}


# U-A5: refresh reuse detected -------------------------------------------------
@respx.mock
def test_refresh_reuse_detected(logged_in_client):
    respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(
        return_value=httpx.Response(401, json={"code": "invalid_token", "message": "reuse"})
    )
    with pytest.raises(AuthenticationError) as exc_info:
        logged_in_client.refresh_token()
    assert exc_info.value.code == "invalid_token"


# U-A6: single-flight refresh fires once under concurrency --------------------
def test_single_flight_refresh_once_under_threads():
    """Many concurrent 401s must collapse into a single refresh.

    Backend refresh tokens are one-time-rotated and reuse-detected, so two
    concurrent refreshes would nuke the whole session. We assert the refresh
    primitive runs the underlying refresh exactly once across many threads that
    all arrive "at the same time".

    We mock ``_do_refresh`` (rather than the /auth/refresh route) so the threads
    genuinely overlap inside the refresh critical section — this is the only way
    to observe single-flight dedup without flaky timing, since a real respx
    transport serializes the requests.
    """
    import threading

    from markpost._models import RefreshTokenResult

    client = Markpost(BASE_URL)
    client._access_token = "tok-access"
    client._refresh_token = "tok-refresh"

    refresh_calls = 0
    refresh_calls_lock = threading.Lock()

    def fake_do_refresh():
        nonlocal refresh_calls
        # Linger inside the refresh critical section so other threads that enter
        # _force_refresh concurrently pile up behind self._refresh_lock.
        time.sleep(0.05)
        with refresh_calls_lock:
            refresh_calls += 1
        result = RefreshTokenResult(
            token="tok-access-2", refresh_token="tok-refresh-2", expires_in=3600
        )
        client._store_refresh(result)
        return result

    client._do_refresh = fake_do_refresh  # type: ignore[method-assign]

    results: list[bool] = []
    errors: list[BaseException] = []

    def worker():
        try:
            ok = client._force_refresh(stale_generation=0)
            results.append(ok)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"unexpected exceptions: {errors}"
    # Every caller observes success (a refreshed token).
    assert all(results)
    # The single-flight guarantee: the underlying refresh ran exactly once.
    assert refresh_calls == 1
    assert client._access_token == "tok-access-2"


# U-A7: refresh failure does not loop -----------------------------------------
@respx.mock
def test_single_flight_refresh_failure_no_loop(logged_in_client):
    respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(
        return_value=httpx.Response(401, json={"code": "invalid_token", "message": "bad"})
    )
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(401, json={"code": "unauthorized", "message": "expired"})
    )
    # Refresh fails -> the original 401 surfaces as AuthenticationError, no loop.
    with pytest.raises(AuthenticationError):
        logged_in_client.list_posts()


# U-A8: auto-login on construction --------------------------------------------
@respx.mock
def test_auto_login_on_construction():
    respx.post(f"{BASE_URL}/api/v1/auth/login").mock(return_value=login_response())
    client = Markpost(BASE_URL, "alice", "secret")
    assert client._access_token == "tok-access"
    assert client._refresh_token == "tok-refresh"


# U-A9: logout clears tokens ---------------------------------------------------
@respx.mock
def test_logout_clears_tokens(logged_in_client):
    respx.post(f"{BASE_URL}/api/v1/auth/logout").mock(
        return_value=httpx.Response(200, json={"message": "bye"})
    )
    assert logged_in_client.logout() is None
    assert logged_in_client._access_token is None
    assert logged_in_client._refresh_token is None


# U-A10: change_password success ----------------------------------------------
@respx.mock
def test_change_password_success(logged_in_client):
    route = respx.post(f"{BASE_URL}/api/v1/auth/change-password").mock(
        return_value=httpx.Response(200, json={"message": "Password changed"})
    )
    msg = logged_in_client.change_password("old", "newpass123")
    assert msg == "Password changed"
    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert body == {"current_password": "old", "new_password": "newpass123"}


# U-A11: change_password 422 too short ----------------------------------------
@respx.mock
def test_change_password_too_short(logged_in_client):
    respx.post(f"{BASE_URL}/api/v1/auth/change-password").mock(
        return_value=httpx.Response(422, json={"code": "password_too_short", "message": "min 6"})
    )
    with pytest.raises(UnprocessableEntityError) as exc_info:
        logged_in_client.change_password("old", "12345")
    assert exc_info.value.code == "password_too_short"


# U-A12: get_post_key caches ---------------------------------------------------
@respx.mock
def test_get_post_key_caches(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/post-key").mock(
        return_value=httpx.Response(
            200, json={"post_key": "mpk-abcdef", "created_at": "2026-01-01T00:00:00Z"}
        )
    )
    key = logged_in_client.get_post_key()
    assert key == "mpk-abcdef"
    assert logged_in_client._post_key == "mpk-abcdef"


# U-A13: 401 auto-refresh retries once ----------------------------------------
@respx.mock
def test_401_auto_refresh_retries_once(logged_in_client):
    refresh = respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(return_value=refresh_response())
    posts = respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.Response(401, json={"code": "unauthorized", "message": "expired"}),
            httpx.Response(
                200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}
            ),
        ]
    )
    result = logged_in_client.list_posts()
    assert result.total == 0
    # Exactly one refresh, and the original request sent exactly twice.
    assert refresh.call_count == 1
    assert posts.call_count == 2


# U-A14: 401 after refresh still fails (no infinite retry) --------------------
@respx.mock
def test_401_after_refresh_still_fails(logged_in_client):
    respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(return_value=refresh_response())
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(401, json={"code": "unauthorized", "message": "no"})
    )
    with pytest.raises(AuthenticationError):
        logged_in_client.list_posts()


# U-A15: proactive refresh when token near expiry -----------------------------
@respx.mock
def test_proactive_refresh_before_request(near_expiry_client):
    refresh = respx.post(f"{BASE_URL}/api/v1/auth/refresh").mock(return_value=refresh_response())
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(
            200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}
        )
    )
    near_expiry_client.list_posts()
    # Proactive refresh fired before the request went out.
    assert refresh.call_count == 1


# Sanity: explicit refresh with no refresh token raises ----------------------
def test_refresh_without_token_raises():
    client = Markpost(BASE_URL)
    with pytest.raises(AuthenticationError):
        client.refresh_token()
