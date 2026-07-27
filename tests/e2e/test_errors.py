"""E2E: real backend error codes (TESTING §5.4.6)."""

from __future__ import annotations

import pytest

from markpost import (
    AuthenticationError,
    Markpost,
    NotFoundError,
    PermissionDeniedError,
    UnprocessableEntityError,
)

pytestmark = pytest.mark.e2e


# E-ER1: unauthenticated request to a protected resource ----------------------
def test_unauthenticated_returns_unauthorized(base_url):
    with Markpost(base_url) as c, pytest.raises(AuthenticationError) as exc_info:
        c.list_posts()
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "unauthorized"


# E-ER2: wrong password -------------------------------------------------------
def test_wrong_password_code(base_url):
    with Markpost(base_url) as c, pytest.raises(AuthenticationError) as exc_info:
        c.login("markpost", "wrong")
    assert exc_info.value.code == "invalid_credentials"


# E-ER3: missing resource -----------------------------------------------------
def test_not_found_code(admin_client):
    with pytest.raises(NotFoundError) as exc_info:
        admin_client.delete_post("p-nonexistent-zzz")
    assert exc_info.value.code == "not_found"


# E-ER4: password too short (backend binding min=6) --------------------------
def test_password_too_short_code(admin_client):
    # 5 chars is below the backend's min=6 binding -> 422 (see SPEC appendix B1).
    with pytest.raises(UnprocessableEntityError) as exc_info:
        admin_client.change_password("markpost", "12345")
    # The binding layer rejects short passwords; code may be 'required'/'min_length'.
    assert exc_info.value.status_code == 422


# E-ER5: invalid post_key -----------------------------------------------------
def test_invalid_post_key_code(admin_client):
    with pytest.raises(PermissionDeniedError) as exc_info:
        admin_client.create_post("t", "b", post_key="mpk-invalid-aaaaaaaaaaaaaaaa")
    assert exc_info.value.code == "invalid_post_key"


# E-ER6: validation body carries errors[] ------------------------------------
def test_validation_errors_array_parsed(admin_client):
    # Empty kind triggers a 422 with an errors[] detail from the binding layer.
    with pytest.raises(UnprocessableEntityError) as exc_info:
        admin_client.create_channel("", "no-kind", {})
    err = exc_info.value
    assert err.status_code == 422
    # The SDK must have parsed the errors array into FieldError objects.
    assert isinstance(err.errors, list)
