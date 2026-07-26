"""Delivery resource methods (TESTING §4.4)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from markpost import UnprocessableEntityError

from .conftest import BASE_URL

CHANNEL_BODY = {
    "id": 1,
    "kind": "feishu",
    "name": "ops",
    "enabled": True,
    "configuration": {"webhook_url": "https://hook", "card_link_url": "https://card"},
    "keywords": "alert",
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-02T00:00:00Z",
}


# U-D1: list_channels -> list (no pagination) ---------------------------------
@respx.mock
def test_list_channels_no_pagination(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/delivery/channels").mock(
        return_value=httpx.Response(200, json={"items": [CHANNEL_BODY, CHANNEL_BODY]})
    )
    result = logged_in_client.list_channels()
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0].id == 1
    assert result[0].kind == "feishu"


# U-D2: create_channel --------------------------------------------------------
@respx.mock
def test_create_channel(logged_in_client):
    route = respx.post(f"{BASE_URL}/api/v1/delivery/channels").mock(
        return_value=httpx.Response(201, json={"channel": CHANNEL_BODY})
    )
    ch = logged_in_client.create_channel(
        "feishu", "ops", {"webhook_url": "https://hook"}, keywords="alert"
    )
    assert ch.id == 1
    sent = route.calls.last.request
    body = json.loads(sent.content)
    assert body["kind"] == "feishu"
    assert body["name"] == "ops"
    assert body["keywords"] == "alert"
    assert body["configuration"] == {"webhook_url": "https://hook"}


# U-D3: create_channel 422 ----------------------------------------------------
@respx.mock
def test_create_channel_missing_kind(logged_in_client):
    respx.post(f"{BASE_URL}/api/v1/delivery/channels").mock(
        return_value=httpx.Response(422, json={"code": "required", "message": "kind required"})
    )
    with pytest.raises(UnprocessableEntityError):
        logged_in_client.create_channel("", "ops", {})


# U-D4: update_channel PATCH only sends given fields --------------------------
@respx.mock
def test_update_channel_patch_semantics(logged_in_client):
    route = respx.patch(f"{BASE_URL}/api/v1/delivery/channels/1").mock(
        return_value=httpx.Response(200, json={"channel": {**CHANNEL_BODY, "enabled": False}})
    )
    ch = logged_in_client.update_channel(1, enabled=False)
    assert ch.enabled is False
    sent = route.calls.last.request
    body = json.loads(sent.content)
    # Body must contain ONLY enabled (PATCH semantics).
    assert body == {"enabled": False}


# U-D5: update_channel with no fields -----------------------------------------
@respx.mock
def test_update_channel_all_omitted(logged_in_client):
    route = respx.patch(f"{BASE_URL}/api/v1/delivery/channels/1").mock(
        return_value=httpx.Response(200, json={"channel": CHANNEL_BODY})
    )
    ch = logged_in_client.update_channel(1)
    assert ch.id == 1
    assert route.called


# U-D6: delete_channel --------------------------------------------------------
@respx.mock
def test_delete_channel(logged_in_client):
    route = respx.delete(f"{BASE_URL}/api/v1/delivery/channels/1").mock(
        return_value=httpx.Response(204)
    )
    assert logged_in_client.delete_channel(1) is None
    assert route.called


# U-D7: list_delivery_history default -----------------------------------------
@respx.mock
def test_list_delivery_history_default(logged_in_client):
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
    page = logged_in_client.list_delivery_history()
    assert len(page.items) == 1
    assert page.items[0].status == "delivered"


# U-D8: list_delivery_history with channel_id ---------------------------------
@respx.mock
def test_list_delivery_history_channel_id(logged_in_client):
    route = respx.get(f"{BASE_URL}/api/v1/delivery/history").mock(
        return_value=httpx.Response(
            200,
            json={"items": [], "total": 0, "page": 1, "limit": 20, "total_pages": 0},
        )
    )
    logged_in_client.list_delivery_history(channel_id=42)
    url = str(route.calls.last.request.url)
    assert "channel_id=42" in url


# U-D9: history item nullable fields ------------------------------------------
@respx.mock
def test_history_nullable_fields(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/delivery/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "status": "failed",
                        "last_error": "timeout",
                        "created_at": "2026-01-01T00:00:00Z",
                        "post_title": None,
                        "post_qid": None,
                        "channel_name": None,
                        "username": None,
                    }
                ],
                "total": 1,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    page = logged_in_client.list_delivery_history()
    item = page.items[0]
    assert item.post_title is None
    assert item.channel_name is None


# U-D10: configuration is passed through verbatim -----------------------------
@respx.mock
def test_configuration_pass_through(logged_in_client):
    route = respx.post(f"{BASE_URL}/api/v1/delivery/channels").mock(
        return_value=httpx.Response(201, json={"channel": CHANNEL_BODY})
    )
    custom_cfg = {"webhook_url": "x", "arbitrary_key": {"nested": [1, 2, 3]}}
    logged_in_client.create_channel("feishu", "ops", custom_cfg)
    sent = route.calls.last.request
    # The dynamic object must be serialized verbatim, not coerced.
    assert b"arbitrary_key" in sent.content
    assert b"nested" in sent.content


# U-D11: test_channel sends POST and returns the message ----------------------
@respx.mock
def test_test_channel(logged_in_client):
    route = respx.post(f"{BASE_URL}/api/v1/delivery/channels/1/test").mock(
        return_value=httpx.Response(200, json={"message": "test message sent"})
    )
    msg = logged_in_client.test_channel(1)
    assert msg == "test message sent"
    assert route.called


# U-D12: list_latest_delivery -> list (no pagination) -------------------------
@respx.mock
def test_list_latest_delivery_no_pagination(logged_in_client):
    respx.get(f"{BASE_URL}/api/v1/delivery/latest").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 7,
                        "status": "delivered",
                        "last_error": "",
                        "created_at": "2026-01-01T00:00:00Z",
                        "channel_id": 1,
                        "channel_name": "ops",
                    }
                ]
            },
        )
    )
    result = logged_in_client.list_latest_delivery()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].channel_id == 1
    assert result[0].channel_name == "ops"


# U-D13: history item channel_id is parsed (incl. nullable) -------------------
@respx.mock
def test_history_item_channel_id_field(logged_in_client):
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
                        "channel_id": 42,
                    },
                    {
                        "id": 2,
                        "status": "delivered",
                        "last_error": "",
                        "created_at": "2026-01-01T00:00:00Z",
                        "channel_id": None,
                    },
                ],
                "total": 2,
                "page": 1,
                "limit": 20,
                "total_pages": 1,
            },
        )
    )
    page = logged_in_client.list_delivery_history()
    assert page.items[0].channel_id == 42
    assert page.items[1].channel_id is None
