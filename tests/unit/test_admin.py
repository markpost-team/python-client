"""Admin resource methods (TESTING §4.5)."""

from __future__ import annotations

import httpx
import pytest
import respx

from markpost import PermissionDeniedError

from .conftest import BASE_URL


# U-AD1: admin_list_users ------------------------------------------------------
@respx.mock
def test_admin_list_users(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/admin/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "username": "markpost",
                        "email": "root@markpost.cc",
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
    page = logged_in_client.admin_list_users()
    assert page.items[0].role == "admin"
    assert page.items[0].is_active is True


# U-AD2: admin_list_posts with search -----------------------------------------
@respx.mock
def test_admin_list_posts_with_search(logged_in_client):
    route = respx.get(f"{BASE_URL}/api/v1/admin/posts").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "qid": "p-a",
                        "title": "alert runbook",
                        "user_id": 1,
                        "username": "alice",
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
    page = logged_in_client.admin_list_posts(search="alert")
    assert page.items[0].qid == "p-a"
    url = str(route.calls.last.request.url)
    assert "search=alert" in url


# U-AD3: admin_delete_post -----------------------------------------------------
@respx.mock
def test_admin_delete_post(logged_in_client):
    route = respx.delete(f"{BASE_URL}/api/v1/admin/posts/p-a").mock(return_value=httpx.Response(204))
    assert logged_in_client.admin_delete_post("p-a") is None
    assert route.called


# U-AD4: admin 403 for non-admin ----------------------------------------------
@respx.mock
def test_admin_forbidden(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/admin/users").mock(
        return_value=httpx.Response(403, json={"code": "forbidden", "message": "admin only"})
    )
    with pytest.raises(PermissionDeniedError):
        logged_in_client.admin_list_users()


# U-AD5: admin_list_channels / admin_list_delivery_history --------------------
@respx.mock
def test_admin_list_channels(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/admin/delivery/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "name": "ops",
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
    page = logged_in_client.admin_list_channels()
    assert page.items[0].user_id == 1


@respx.mock
def test_admin_list_delivery_history(logged_in_client):
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
    page = logged_in_client.admin_list_delivery_history()
    assert page.items[0].status == "delivered"
