"""Model instantiation (TESTING §4.8)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from markpost import (
    AdminChannel,
    AdminPost,
    AdminUser,
    AuthResult,
    Channel,
    DeliveryHistoryItem,
    Page,
    PostCreated,
    PostListItem,
    User,
)


def _user_body(**over: object) -> dict[str, object]:
    base = {
        "id": 1,
        "email": "a@b.c",
        "username": "u",
        "name": "n",
        "avatar_url": None,
        "role": "admin",
    }
    base.update(over)
    return base


# U-M1: models instantiate from sample JSON ------------------------------------
@pytest.mark.parametrize(
    "model,body",
    [
        (User, _user_body()),
        (
            AuthResult,
            {"user": _user_body(), "token": "t", "refresh_token": "r", "expires_in": 3600},
        ),
        (PostCreated, {"id": "p-abc123"}),
        (
            PostListItem,
            {"id": 1, "qid": "p-abc", "title": "T", "created_at": "2026-01-01T00:00:00Z"},
        ),
        (
            Channel,
            {
                "id": 1,
                "kind": "feishu",
                "name": "n",
                "enabled": True,
                "configuration": {"webhook_url": "x"},
                "keywords": "",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
            },
        ),
        (
            DeliveryHistoryItem,
            {
                "id": 1,
                "status": "delivered",
                "last_error": "",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ),
        (
            AdminUser,
            {
                "id": 1,
                "username": "u",
                "email": "e",
                "role": "admin",
                "is_active": True,
                "created_at": "2026-01-01T00:00:00Z",
            },
        ),
        (
            AdminPost,
            {
                "qid": "p-x",
                "title": "t",
                "user_id": 1,
                "username": "u",
                "created_at": "2026-01-01T00:00:00Z",
            },
        ),
        (
            AdminChannel,
            {
                "id": 1,
                "name": "n",
                "kind": "feishu",
                "enabled": True,
                "user_id": 1,
                "configuration": {},
                "created_at": "2026-01-01T00:00:00Z",
            },
        ),
    ],
)
def test_model_instantiation(model, body):
    obj = model.model_validate(body)
    assert obj is not None


# U-M2: extra fields tolerated (extra="ignore") -------------------------------
def test_extra_fields_ignored():
    obj = User.model_validate({**_user_body(), "unexpected_field": "x", "another": 123})
    assert not hasattr(obj, "unexpected_field")


def test_extra_fields_ignored_in_page():
    # backend paginated responses may carry extra keys; Page must not choke.
    body = {
        "items": [],
        "total": 0,
        "page": 1,
        "limit": 20,
        "total_pages": 0,
        "meta": "ignored",
    }
    page = Page[PostListItem].model_validate(body)
    assert page.items == []


# U-M3: datetime parsing -------------------------------------------------------
def test_datetime_parsing():
    obj = PostListItem.model_validate({"id": 1, "qid": "p-a", "title": "t", "created_at": "2026-07-24T12:00:00Z"})
    assert obj.created_at == datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


# U-M4: Page generic -----------------------------------------------------------
def test_page_generic_parses_nested_items():
    body = {
        "items": [
            {"id": 1, "qid": "p-a", "title": "A", "created_at": "2026-01-01T00:00:00Z"},
            {"id": 2, "qid": "p-b", "title": "B", "created_at": "2026-01-02T00:00:00Z"},
        ],
        "total": 2,
        "page": 1,
        "limit": 20,
        "total_pages": 1,
    }
    page = Page[PostListItem].model_validate(body)
    assert len(page.items) == 2
    assert isinstance(page.items[0], PostListItem)
    assert page.items[1].qid == "p-b"
    assert page.total_pages == 1


# U-M5: nullable fields --------------------------------------------------------
def test_nullable_fields_become_none():
    item = DeliveryHistoryItem.model_validate(
        {
            "id": 1,
            "status": "failed",
            "last_error": "boom",
            "created_at": "2026-01-01T00:00:00Z",
            "post_title": None,
            "post_qid": None,
            "channel_name": None,
            "username": None,
        }
    )
    assert item.post_title is None
    assert item.post_qid is None
    assert item.channel_name is None
    assert item.username is None


def test_user_avatar_url_nullable():
    obj = User.model_validate(_user_body(avatar_url=None))
    assert obj.avatar_url is None
    obj2 = User.model_validate(_user_body(avatar_url="https://x/a.png"))
    assert obj2.avatar_url == "https://x/a.png"
