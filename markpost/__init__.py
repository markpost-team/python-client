"""Markpost Python SDK.

A typed, sync + async client for the Markpost API.

Quick start (sync)::

    from markpost import Markpost
    with Markpost("https://markpost.cc", "user", "pass") as client:
        created = client.create_post("Hello", "# body")

Quick start (async)::

    from markpost import AsyncMarkpost
    async with AsyncMarkpost("https://markpost.cc", "user", "pass") as client:
        created = await client.create_post("Hello", "# body")
"""

from __future__ import annotations

from ._async import AsyncMarkpost
from ._exceptions import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    FieldError,
    InternalServerError,
    MarkpostError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from ._models import (
    AdminChannel,
    AdminPost,
    AdminUser,
    AuthResult,
    Channel,
    DeliveryHistoryItem,
    FeishuConfig,
    Page,
    PostCreated,
    PostKeyResult,
    PostListItem,
    RefreshTokenResult,
    User,
)
from ._sync import Markpost

__version__ = "0.2.0-rc.2"

__all__ = [
    # Clients
    "AsyncMarkpost",
    "Markpost",
    # Models
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
    # Exceptions
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "FieldError",
    "InternalServerError",
    "MarkpostError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "UnprocessableEntityError",
    # Meta
    "__version__",
]
