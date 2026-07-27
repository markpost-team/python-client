"""E2E: auth flows with real token rotation (TESTING §5.4.2).

The admin identity is reset before/after every e2e test by the
``_isolate_admin_identity`` autouse fixture in conftest.py, so the state-mutating
tests below (refresh rotation, logout, change_password) cannot poison each other.
"""

from __future__ import annotations

import pytest

from markpost import AuthenticationError, Markpost

pytestmark = pytest.mark.e2e

ADMIN_USER = "markpost"
ADMIN_PASS = "markpost"


def _client(base_url):
    return Markpost(base_url)


# E-A1 ------------------------------------------------------------------------
def test_login_success(base_url):
    with _client(base_url) as c:
        result = c.login(ADMIN_USER, ADMIN_PASS)
    assert result.token
    assert result.user.role == "admin"


# E-A2 ------------------------------------------------------------------------
def test_login_wrong_password(base_url):
    with _client(base_url) as c, pytest.raises(AuthenticationError) as exc_info:
        c.login(ADMIN_USER, "definitely-wrong")
    assert exc_info.value.code == "invalid_credentials"


# E-A3 ------------------------------------------------------------------------
def test_login_unknown_user(base_url):
    with _client(base_url) as c, pytest.raises(AuthenticationError):
        c.login("nobody-exists", "x")


# E-A4 ------------------------------------------------------------------------
def test_get_post_key_prefix(base_url):
    with _client(base_url) as c:
        c.login(ADMIN_USER, ADMIN_PASS)
        key = c.get_post_key()
    assert key.startswith("mpk-")


# E-A5 — the key scenario: refresh is one-time rotation ----------------------
def test_refresh_rotation_is_one_time(base_url):
    with _client(base_url) as c:
        c.login(ADMIN_USER, ADMIN_PASS)
        old_refresh = c._refresh_token
        # First refresh succeeds and issues a new pair.
        c.refresh_token()
        new_refresh = c._refresh_token
        assert new_refresh != old_refresh
        # Replaying the OLD refresh token must be rejected (reuse detection).
        c._refresh_token = old_refresh
        with pytest.raises(AuthenticationError) as exc_info:
            c.refresh_token()
        assert exc_info.value.code == "invalid_token"


# E-A6 ------------------------------------------------------------------------
def test_logout_invalidates_token(base_url):
    with _client(base_url) as c:
        c.login(ADMIN_USER, ADMIN_PASS)
        c.logout()
        # After logout, an authenticated call must fail.
        with pytest.raises(AuthenticationError):
            c.list_posts()


# E-A7 ------------------------------------------------------------------------
def test_change_password_roundtrip(base_url):
    # Change the password, log in with the new one, then restore the original.
    new_pass = "new-e2e-pass-123"
    with _client(base_url) as c:
        c.login(ADMIN_USER, ADMIN_PASS)
        try:
            msg = c.change_password(ADMIN_PASS, new_pass)
            assert msg
            # New password works.
            c2 = _client(base_url)
            c2.__enter__()
            try:
                c2.login(ADMIN_USER, new_pass)
            finally:
                c2.__exit__(None, None, None)
        finally:
            # Restore the original password so other tests keep working.
            c2 = _client(base_url)
            c2.__enter__()
            try:
                c2.login(ADMIN_USER, new_pass)
                c2.change_password(new_pass, ADMIN_PASS)
            finally:
                c2.__exit__(None, None, None)


# E-A8 ------------------------------------------------------------------------
def test_change_password_wrong_current(base_url):
    with _client(base_url) as c:
        c.login(ADMIN_USER, ADMIN_PASS)
        with pytest.raises(AuthenticationError):
            c.change_password("totally-wrong", "newpass123")
