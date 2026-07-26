"""Pydantic v2 models mirroring the Markpost backend response shapes.

Every model uses ``extra="ignore"`` (SPEC §7) so the SDK tolerates fields the
backend adds later without breaking. Time fields are ``datetime`` (pydantic
parses ISO8601). Integer IDs are plain ``int`` regardless of Go-side int/int64.

All field names and shapes are verified against backend source:
``backend/internal/api/rest/v1/types.go``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

# Sentinel TypeVar bound for ``Page[T]``.
T = TypeVar("T")

_MODEL_CONFIG = ConfigDict(extra="ignore")


class User(BaseModel):
    """A user record as returned inside an auth response (types.go:17-24)."""

    model_config = _MODEL_CONFIG

    id: int
    email: str
    username: str
    name: str
    avatar_url: str | None = None
    role: str


class AuthResult(BaseModel):
    """Result of ``login`` / ``refresh_token`` (types.go:45 AuthResponse).

    Note: the ``login`` response includes ``user``; the ``refresh`` response
    (RefreshTokenResponse, types.go:50) does NOT — see :class:`RefreshTokenResult`.
    """

    model_config = _MODEL_CONFIG

    user: User
    token: str
    refresh_token: str
    expires_in: int


class RefreshTokenResult(BaseModel):
    """Result of ``refresh_token`` against the backend (types.go:50).

    The backend's refresh endpoint returns only the new token pair — no ``user``
    — so this is the faithful shape. The public ``refresh_token()`` returns this.
    """

    model_config = _MODEL_CONFIG

    token: str
    refresh_token: str
    expires_in: int


class PostKeyResult(BaseModel):
    """Result of ``get_post_key`` (types.go:56)."""

    model_config = _MODEL_CONFIG

    post_key: str
    created_at: datetime


class PostCreated(BaseModel):
    """Result of ``create_post`` (types.go:96). ``id`` is ``"p-<nanoid>"``."""

    model_config = _MODEL_CONFIG

    id: str


class PostListItem(BaseModel):
    """An item in ``list_posts`` (types.go:101)."""

    model_config = _MODEL_CONFIG

    id: int
    qid: str
    title: str
    created_at: datetime


class Page(BaseModel, Generic[T]):
    """Flat paginated response (common.go:352 ``paginatedResponse``).

    ``items`` is the list of resources for the current page. Note that
    ``list_channels`` does NOT return a Page — it returns a bare ``list``.
    """

    model_config = _MODEL_CONFIG

    items: list[T]
    total: int
    page: int
    limit: int
    total_pages: int


class Channel(BaseModel):
    """A delivery channel (types.go:126 ChannelResponse).

    ``configuration`` is a free-form object (``map[string]any`` in Go);
    the SDK passes it through without strong-typing its keys.
    """

    model_config = _MODEL_CONFIG

    id: int
    kind: str
    name: str
    enabled: bool
    configuration: dict[str, Any]
    keywords: str
    created_at: datetime
    updated_at: datetime


class DeliveryHistoryItem(BaseModel):
    """A delivery-history row (types.go:202).

    The nullable join fields (post_title/post_qid/channel_name/username) are
    ``None`` when the related resource was deleted (FK ON DELETE SET NULL).
    ``channel_id`` is the owning channel of this attempt (nullable for legacy
    rows written before the column existed).
    """

    model_config = _MODEL_CONFIG

    id: int
    status: str  # delivered | failed | expired
    last_error: str
    created_at: datetime
    channel_id: int | None = None
    post_title: str | None = None
    post_qid: str | None = None
    channel_name: str | None = None
    username: str | None = None


class AdminUser(BaseModel):
    """Admin user list item (types.go:248)."""

    model_config = _MODEL_CONFIG

    id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class AdminPost(BaseModel):
    """Admin post list item (types.go:269)."""

    model_config = _MODEL_CONFIG

    qid: str
    title: str
    user_id: int
    username: str
    created_at: datetime


class AdminChannel(BaseModel):
    """Admin channel list item (types.go:288)."""

    model_config = _MODEL_CONFIG

    id: int
    name: str
    kind: str
    enabled: bool
    user_id: int
    configuration: dict[str, Any]
    created_at: datetime


class FeishuConfig(dict[str, Any]):
    """Convenience ``TypedDict``-like helper for building a feishu configuration.

    Not a pydantic model and does NOT participate in validation — the backend
    treats ``configuration`` as a free-form ``map[string]any``. Provided only as
    a documentation/constructor aid (SPEC §6.4).
    """


__all__ = [
    "AdminChannel",
    "AdminPost",
    "AdminUser",
    "AuthResult",
    "Channel",
    "DeliveryHistoryItem",
    "FeishuConfig",
    "Page",
    "PostCreated",
    "PostKeyResult",
    "PostListItem",
    "RefreshTokenResult",
    "User",
]
