"""Posts resource methods (TESTING §4.3)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from markpost import NotFoundError, PermissionDeniedError, UnprocessableEntityError

from .conftest import BASE_URL


# U-P1: create_post success posts to root-level /{post_key} (no /api/v1) ------
@respx.mock
def test_create_post_success(logged_in_client):
    # Match the root-level path with the post_key, NOT /api/v1.
    route = respx.post(f"{BASE_URL}/mpk-mykey").mock(return_value=httpx.Response(201, json={"id": "p-abc123"}))
    result = logged_in_client.create_post("Title", "body", post_key="mpk-mykey")
    assert result.id == "p-abc123"
    sent = route.calls.last.request
    assert sent.url.path == "/mpk-mykey"  # root-level, not /api/v1
    body = json.loads(sent.content)
    assert body == {"title": "Title", "body": "body"}


# U-P2: create_post without post_key auto-fetches ----------------------------
@respx.mock
def test_create_post_auto_fetches_post_key(logged_in_client):
    pk = respx.get(f"{BASE_URL}/api/v1/post-key").mock(
        return_value=httpx.Response(200, json={"post_key": "mpk-fetched", "created_at": "2026-01-01T00:00:00Z"})
    )
    create = respx.post(f"{BASE_URL}/mpk-fetched").mock(return_value=httpx.Response(201, json={"id": "p-xyz"}))
    result = logged_in_client.create_post("T", "B")
    assert result.id == "p-xyz"
    assert pk.call_count == 1
    assert create.call_count == 1
    # And the fetched key is cached for subsequent calls.
    assert logged_in_client._post_key == "mpk-fetched"


# U-P3: explicit post_key skips get_post_key ---------------------------------
@respx.mock
def test_create_post_explicit_key_skips_fetch(logged_in_client):
    pk = respx.get(f"{BASE_URL}/api/v1/post-key").mock(
        return_value=httpx.Response(200, json={"post_key": "mpk-x", "created_at": "2026-01-01T00:00:00Z"})
    )
    respx.post(f"{BASE_URL}/mpk-explicit").mock(return_value=httpx.Response(201, json={"id": "p-1"}))
    logged_in_client.create_post("T", "B", post_key="mpk-explicit")
    assert pk.call_count == 0


# U-P4: create_post 403 --------------------------------------------------------
@respx.mock
def test_create_post_invalid_post_key(logged_in_client):
    respx.post(f"{BASE_URL}/mpk-bad").mock(
        return_value=httpx.Response(403, json={"code": "invalid_post_key", "message": "no"})
    )
    with pytest.raises(PermissionDeniedError) as exc_info:
        logged_in_client.create_post("T", "B", post_key="mpk-bad")
    assert exc_info.value.code == "invalid_post_key"


# U-P5: create_post 422 --------------------------------------------------------
@respx.mock
def test_create_post_title_too_long(logged_in_client):
    respx.post(f"{BASE_URL}/mpk-k").mock(
        return_value=httpx.Response(422, json={"code": "title_too_long", "message": "too long"})
    )
    with pytest.raises(UnprocessableEntityError) as exc_info:
        logged_in_client.create_post("T" * 9999, "B", post_key="mpk-k")
    assert exc_info.value.code == "title_too_long"


# U-P14: create_post carries NO Authorization header --------------------------
@respx.mock
def test_create_post_has_no_jwt_header(logged_in_client):
    route = respx.post(f"{BASE_URL}/mpk-k").mock(return_value=httpx.Response(201, json={"id": "p-1"}))
    logged_in_client.create_post("T", "B", post_key="mpk-k")
    sent = route.calls.last.request
    assert "authorization" not in {k.lower() for k in sent.headers}


# U-P6: get_post html returns str ---------------------------------------------
@respx.mock
def test_get_post_html(logged_in_client):
    respx.get(f"{BASE_URL}/p-abc").mock(return_value=httpx.Response(200, text="<html><h1>Hi</h1></html>"))
    result = logged_in_client.get_post("p-abc")
    assert isinstance(result, str)
    assert "<html>" in result


# U-P7: get_post raw returns markdown str -------------------------------------
@respx.mock
def test_get_post_raw(logged_in_client):
    route = respx.get(f"{BASE_URL}/p-abc").mock(return_value=httpx.Response(200, text="# Title\n\nbody"))
    result = logged_in_client.get_post("p-abc", format="raw")
    assert isinstance(result, str)
    assert result.startswith("# Title")
    # format=raw was sent as a query param.
    assert "format=raw" in str(route.calls.last.request.url)


# U-P8: get_post 304 returns None ---------------------------------------------
@respx.mock
def test_get_post_304_returns_none(logged_in_client):
    respx.get(f"{BASE_URL}/p-abc").mock(return_value=httpx.Response(304))
    result = logged_in_client.get_post("p-abc", if_none_match='"etag-xyz"')
    assert result is None


# U-P9: get_post 404 -----------------------------------------------------------
@respx.mock
def test_get_post_not_found(logged_in_client):
    respx.get(f"{BASE_URL}/p-none").mock(
        return_value=httpx.Response(404, json={"code": "not_found", "message": "missing"})
    )
    with pytest.raises(NotFoundError):
        logged_in_client.get_post("p-none")


# U-P10: list_posts default pagination ----------------------------------------
@respx.mock
def test_list_posts_default_pagination(logged_in_client):
    route = respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"id": 1, "qid": "p-a", "title": "A", "created_at": "2026-01-01T00:00:00Z"}],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    page = logged_in_client.list_posts()
    assert len(page.items) == 1
    assert page.items[0].qid == "p-a"
    assert page.total == 1
    # Default page=1&limit=20.
    url = str(route.calls.last.request.url)
    assert "page=1" in url
    assert "limit=20" in url


# U-P11: list_posts custom pagination -----------------------------------------
@respx.mock
def test_list_posts_custom_pagination(logged_in_client):
    route = respx.get(f"{BASE_URL}/api/v1/posts").mock(
        return_value=httpx.Response(
            200,
            json={"items": [], "total": 100, "page": 3, "limit": 50, "total_pages": 2},
        )
    )
    page = logged_in_client.list_posts(page=3, limit=50)
    assert page.page == 3
    assert page.limit == 50
    url = str(route.calls.last.request.url)
    assert "page=3" in url
    assert "limit=50" in url


# U-P12: delete_post returns None ---------------------------------------------
@respx.mock
def test_delete_post(logged_in_client):
    route = respx.delete(f"{BASE_URL}/api/v1/posts/p-abc").mock(return_value=httpx.Response(204))
    assert logged_in_client.delete_post("p-abc") is None
    assert route.called


# U-P13: delete_post 404 -------------------------------------------------------
@respx.mock
def test_delete_post_not_found(logged_in_client):
    respx.delete(f"{BASE_URL}/api/v1/posts/p-x").mock(
        return_value=httpx.Response(404, json={"code": "not_found", "message": "no"})
    )
    with pytest.raises(NotFoundError):
        logged_in_client.delete_post("p-x")
