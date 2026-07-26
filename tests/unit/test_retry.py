"""Retry / timeout / backoff behaviour (TESTING §4.6).

All sleeps are monkeypatched so the tests are fast and deterministic. We
patch ``time.sleep`` (sync) and the random jitter is bounded in a dedicated test.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from markpost import APIConnectionError, APITimeoutError, BadRequestError, Markpost, NotFoundError
from markpost._constants import DEFAULT_MAX_RETRIES, RETRY_BASE_DELAY, RETRY_MAX_DELAY

from .conftest import BASE_URL


@pytest.fixture
def patched_sleep(monkeypatch):
    """Replace time.sleep with a no-op recorder that returns call intervals."""
    calls: list[float] = []
    monkeypatch.setattr("markpost._sync.time.sleep", lambda s: calls.append(s))
    return calls


# U-R1: timeout retried, then success -----------------------------------------
@respx.mock
def test_timeout_retried_then_success(logged_in_client, patched_sleep):
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.ConnectTimeout("timed out"),
            httpx.Response(
                200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}
            ),
        ]
    )
    result = logged_in_client.list_posts()
    assert result.total == 0
    assert len(patched_sleep) == 1  # one backoff sleep before the retry


# U-R2: timeout exhausts retries -> APITimeoutError --------------------------
@respx.mock
def test_timeout_exhausts_retries(logged_in_client, patched_sleep):
    respx.get(f"{BASE_URL}/api/v1/posts").mock(side_effect=httpx.ConnectTimeout("down"))
    with pytest.raises(APITimeoutError):
        logged_in_client.list_posts()
    # max_retries + 1 attempts total.
    assert respx.get(f"{BASE_URL}/api/v1/posts").call_count == DEFAULT_MAX_RETRIES + 1


# U-R3: connection error retried, then success --------------------------------
@respx.mock
def test_connection_error_retried_then_success(logged_in_client, patched_sleep):
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.ConnectError("refused"),
            httpx.Response(
                200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}
            ),
        ]
    )
    result = logged_in_client.list_posts()
    assert result.total == 0


# U-R4: 429 retried respecting RateLimit-Reset --------------------------------
@respx.mock
def test_429_retried_respecting_reset_header(logged_in_client, patched_sleep):
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.Response(
                429,
                json={"code": "rate_limited", "message": "slow"},
                headers={"RateLimit-Reset": "3"},
            ),
            httpx.Response(
                200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}
            ),
        ]
    )
    result = logged_in_client.list_posts()
    assert result.total == 0
    # The backoff for a 429 with a valid Reset header (<= margin) must equal it.
    assert patched_sleep == [3.0]


# U-R5: 500 retried ------------------------------------------------------------
@respx.mock
def test_500_retried(logged_in_client, patched_sleep):
    respx.get(f"{BASE_URL}/api/v1/posts").mock(
        side_effect=[
            httpx.Response(500, json={"code": "internal", "message": "boom"}),
            httpx.Response(
                200, json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0}
            ),
        ]
    )
    result = logged_in_client.list_posts()
    assert result.total == 0


# U-R6: 400 not retried --------------------------------------------------------
@respx.mock
def test_400_not_retried(logged_in_client, patched_sleep):
    route = respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(400, json={"code": "invalid_request", "message": "bad"})
    )
    with pytest.raises(BadRequestError):
        logged_in_client.list_posts()
    assert route.call_count == 1
    assert patched_sleep == []


# U-R7: 404 not retried --------------------------------------------------------
@respx.mock
def test_404_not_retried(logged_in_client, patched_sleep):
    respx.delete(f"{BASE_URL}/api/v1/posts/p-x").mock(
        return_value=httpx.Response(404, json={"code": "not_found", "message": "no"})
    )
    with pytest.raises(NotFoundError):
        logged_in_client.delete_post("p-x")
    assert patched_sleep == []


# U-R8: max_retries=0 disables retry ------------------------------------------
@respx.mock
def test_max_retries_zero_disables_retry(patched_sleep):
    client = Markpost(BASE_URL, max_retries=0)
    client._access_token = "t"
    client._refresh_token = "r"
    client._token_expires_at = float("inf")
    route = respx.get(f"{BASE_URL}/api/v1/posts").mock(side_effect=httpx.ConnectTimeout("down"))
    with pytest.raises(APITimeoutError):
        client.list_posts()
    assert route.call_count == 1
    assert patched_sleep == []


# U-R9: exponential backoff grows ---------------------------------------------
@respx.mock
def test_backoff_grows_exponentially(logged_in_client, patched_sleep, monkeypatch):
    # Remove jitter so the formula is deterministic: BASE * 2**n.
    monkeypatch.setattr("markpost._base_client.random.random", lambda: 0.0)
    respx.get(f"{BASE_URL}/api/v1/posts").mock(side_effect=httpx.ConnectTimeout("down"))
    with pytest.raises(APITimeoutError):
        logged_in_client.list_posts()
    # DEFAULT_MAX_RETRIES=2 -> two sleeps: BASE*2**0, BASE*2**1.
    assert patched_sleep == [RETRY_BASE_DELAY * 1, RETRY_BASE_DELAY * 2]


# U-R10: jitter range [0.75*base, 1.0*base) ------------------------------------
def test_jitter_range():

    client = Markpost(BASE_URL)
    # Build a dummy APIConnectionError-like object carrying no rate-limit info.
    exc = APIConnectionError("x")
    base = RETRY_BASE_DELAY  # n=0 -> raw delay = BASE
    samples = [client._calculate_retry_delay(exc, 0) for _ in range(500)]
    for s in samples:
        assert 0.75 * base <= s < 1.0 * base
    assert max(samples) < 1.0 * base
    assert min(samples) >= 0.75 * base


# U-R11: default timeout is non-None and matches config ----------------------
def test_default_timeout_applied():
    client = Markpost(BASE_URL)
    # The internal httpx client must carry a real timeout, not None.
    assert client._http.timeout is not None
    assert client._http.timeout.connect == 5.0
    assert client._http.timeout.read == 30.0


# U-R12: custom timeout overrides default -------------------------------------
def test_custom_timeout_overrides():
    client = Markpost(BASE_URL, timeout=42.0)
    assert client._http.timeout.read == 42.0


# Backoff is capped at RETRY_MAX_DELAY ----------------------------------------
@respx.mock
def test_backoff_capped_at_max(logged_in_client, patched_sleep, monkeypatch):
    monkeypatch.setattr("markpost._base_client.random.random", lambda: 0.0)
    # Force many retries via a large max_retries to exceed the cap.
    client = Markpost(BASE_URL, max_retries=8)
    client._access_token = "t"
    client._refresh_token = "r"
    client._token_expires_at = float("inf")
    respx.get(f"{BASE_URL}/api/v1/posts").mock(side_effect=httpx.ConnectTimeout("down"))
    with pytest.raises(APITimeoutError):
        client.list_posts()
    # No single delay may exceed RETRY_MAX_DELAY (after jitter, <= MAX).
    for s in patched_sleep:
        assert s <= RETRY_MAX_DELAY
