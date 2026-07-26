"""Shared fixtures and sample data for the unit tests.

respx mocks httpx at the transport layer, so the same route declarations serve
both sync (``httpx.Client``) and async (``httpx.AsyncClient``) tests.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from markpost import AsyncMarkpost, Markpost

BASE_URL = "https://test.markpost.cc"

SAMPLE_USER = {
    "id": 1,
    "email": "alice@example.com",
    "username": "alice",
    "name": "Alice",
    "avatar_url": None,
    "role": "admin",
}
SAMPLE_TOKENS = {"token": "tok-access", "refresh_token": "tok-refresh", "expires_in": 3600}


def login_response(**overrides: Any) -> httpx.Response:
    """A 200 login body (AuthResponse)."""
    body = {"user": SAMPLE_USER, **SAMPLE_TOKENS, **overrides}
    return httpx.Response(200, json=body)


def refresh_response(**overrides: Any) -> httpx.Response:
    """A 200 refresh body (RefreshTokenResponse). Rotated token pair."""
    body = {
        "token": "tok-access-2",
        "refresh_token": "tok-refresh-2",
        "expires_in": 3600,
        **overrides,
    }
    return httpx.Response(200, json=body)


@pytest.fixture
def base_url() -> str:
    return BASE_URL


@pytest.fixture
def sample_user():
    return SAMPLE_USER


@pytest.fixture
def sample_tokens():
    return SAMPLE_TOKENS


@pytest.fixture
def login_route():
    """A successful login route, reusable across tests."""
    return respx.post(f"{BASE_URL}/api/v1/auth/login").mock(return_value=login_response())


@pytest.fixture
def logged_in_client() -> Markpost:
    """A sync client that is already authenticated (no real login call).

    We set token state directly so tests focus on the method under test rather
    than the login dance. Token has plenty of headroom before expiry.
    """
    client = Markpost(BASE_URL)
    client._access_token = "tok-access"
    client._refresh_token = "tok-refresh"
    client._token_expires_at = float("inf")  # never expires within a test
    return client


@pytest.fixture
def logged_in_async_client() -> AsyncMarkpost:
    """An async client that is already authenticated (no real login call)."""
    client = AsyncMarkpost(BASE_URL)
    client._access_token = "tok-access"
    client._refresh_token = "tok-refresh"
    client._token_expires_at = float("inf")
    return client


@pytest.fixture
def near_expiry_client() -> Markpost:
    """A sync client whose access token is about to expire (< 60s)."""
    client = Markpost(BASE_URL)
    client._access_token = "tok-access"
    client._refresh_token = "tok-refresh"
    client._token_expires_at = 0.0  # monotonic() is always > 0 -> always expiring
    return client
