"""Asynchronous Markpost client.

A line-for-line mirror of ``_sync.py`` with the four blocking operations
swapped to their async equivalents (SPEC §3.1 / §5). All non-blocking logic is
inherited from :class:`_BaseClient`.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

import anyio
import httpx
from pydantic import BaseModel, ConfigDict

from ._base_client import _BaseClient
from ._constants import DEFAULT_MAX_RETRIES
from ._exceptions import APIError, AuthenticationError
from ._models import (
    AdminChannel,
    AdminPost,
    AdminUser,
    AuthResult,
    Channel,
    DeliveryHistoryItem,
    Page,
    PostCreated,
    PostKeyResult,
    PostListItem,
    RefreshTokenResult,
)

if TYPE_CHECKING:
    from types import TracebackType

    from ._base_client import AuthMode

__all__ = ["AsyncMarkpost"]

_CFG = ConfigDict(extra="ignore")
_T = TypeVar("_T")


# --- internal response wrappers (mirror the sync module) ------------------------


class _ItemsList(BaseModel, Generic[_T]):
    """``{items: [...]}`` wrapper (e.g. ChannelsListResponse has no pagination)."""

    model_config = _CFG
    items: list[_T]


class _ChannelWrapper(BaseModel):
    """``{channel: {...}}`` wrapper (create/update channel responses)."""

    model_config = _CFG
    channel: Channel


class _MessageResponse(BaseModel):
    """``{message: str}`` body (logout / change-password)."""

    model_config = _CFG
    message: str = ""


class _StatusResponse(BaseModel):
    """``{status: str}`` body (health)."""

    model_config = _CFG
    status: str


class AsyncMarkpost(_BaseClient[httpx.AsyncClient]):
    """Asynchronous client for the Markpost API.

    Mirrors :class:`markpost.Markpost` exactly, with ``async``/``await`` on the
    blocking operations::

        async with AsyncMarkpost("https://markpost.cc", "u", "p") as client:
            created = await client.create_post("Hello", "# body")
    """

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        *,
        timeout: float | httpx.Timeout | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        post_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        verify: bool = True,
    ) -> None:
        self._verify = verify
        super().__init__(
            base_url,
            timeout=timeout,
            max_retries=max_retries,
            post_key=post_key,
            http_client=http_client,
        )
        self._refresh_lock = asyncio.Lock()
        # Construction is synchronous (no event loop yet), so auto-login is
        # deferred: when credentials are supplied we stash them and perform the
        # login on the first authenticated call (or on __aenter__). This keeps
        # the "passing username+password auto-logs in" contract from SPEC §10.2
        # while never doing I/O in __init__.
        self._pending_login: tuple[str, str] | None = None
        if username and password:
            self._pending_login = (username, password)

    async def _ensure_logged_in(self) -> None:
        """Run a deferred auto-login once, if credentials were given at construction."""
        if self._pending_login is not None:
            creds, self._pending_login = self._pending_login, None
            await self.login(*creds)

    # ------------------------------------------------------------------ #
    # Subclass hooks (the blocking operations — async variants)
    # ------------------------------------------------------------------ #
    def _make_http(self, timeout: float | httpx.Timeout) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, verify=self._verify)

    async def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            await anyio.sleep(seconds)

    async def _send(self, request: httpx.Request) -> httpx.Response:
        return await self._http.send(request)

    async def aclose(self) -> None:
        """Close the underlying async HTTP client."""
        await self._http.aclose()

    async def __aenter__(self) -> AsyncMarkpost:
        await self._ensure_logged_in()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Single-flight refresh (async) — mirror of sync, R3 guard preserved
    # ------------------------------------------------------------------ #
    async def _refresh_if_needed(self) -> bool:
        async with self._refresh_lock:
            if self._access_token and not self._is_token_expiring():
                return True
            if not self._refresh_token:
                return False
            try:
                await self._do_refresh()
                return True
            except Exception:
                return False

    async def _force_refresh(self, stale_generation: int) -> bool:
        """Reactive single-flight refresh (async), triggered by a 401.

        Mirrors the sync ``_force_refresh``: only refresh if the token hasn't
        been rotated past ``stale_generation`` by a concurrent coroutine, so
        many concurrent 401s collapse into one refresh call.
        """
        async with self._refresh_lock:
            if self._refresh_generation != stale_generation:
                return True
            if not self._refresh_token:
                return False
            try:
                await self._do_refresh()
                return True
            except Exception:
                return False

    async def _do_refresh(self) -> RefreshTokenResult:
        # Bypass _request's 401 handling (SPEC R3 — avoid async deadlock).
        # Backend RefreshTokenResponse has no `user` field.
        request = self._build_request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": self._refresh_token},
            auth="none",
        )
        response = await self._send(request)
        self._raise_for_status(response)
        result = RefreshTokenResult.model_validate(response.json())
        self._store_refresh(result)
        return result

    # ------------------------------------------------------------------ #
    # Request pipeline (async mirror of M3-2)
    # ------------------------------------------------------------------ #
    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: AuthMode = "jwt",
        json: Any | None = None,
        params: Any | None = None,
        model: Any = None,
        text: bool = False,
        extra_headers: dict[str, str] | None = None,
        allow_304: bool = False,
    ) -> Any:
        # Run a deferred construction-time auto-login, if any, before the first
        # authenticated request. Login itself uses auth="none", so this guard
        # only fires once and is a no-op thereafter.
        if self._pending_login is not None:
            await self._ensure_logged_in()
        if auth == "jwt" and self._access_token and self._is_token_expiring():
            await self._refresh_if_needed()

        retries = 0
        retried_401 = False
        while True:
            sent_generation = self._refresh_generation
            request = self._build_request(
                method,
                path,
                json=json,
                params=params,
                auth=auth,
                extra_headers=extra_headers,
            )
            try:
                response = await self._send(request)
            except httpx.TimeoutException as e:
                exc: APIError = cast("APIError", APIError._timeout(str(e) or "Request timed out"))
                if retries < self.max_retries and self._should_retry(exc):
                    await self._sleep(self._calculate_retry_delay(exc, retries))
                    retries += 1
                    continue
                raise exc from e
            except httpx.TransportError as e:
                exc = cast("APIError", APIError._connection(str(e) or "Connection error"))
                if retries < self.max_retries and self._should_retry(exc):
                    await self._sleep(self._calculate_retry_delay(exc, retries))
                    retries += 1
                    continue
                raise exc from e

            if allow_304 and response.status_code == 304:
                return None

            if (
                response.status_code == 401
                and auth == "jwt"
                and self._refresh_token
                and not retried_401
            ):
                retried_401 = True
                if await self._force_refresh(sent_generation):
                    continue

            if not (200 <= response.status_code < 300):
                exc = APIError.from_response(response)
                if retries < self.max_retries and self._should_retry(exc):
                    await self._sleep(self._calculate_retry_delay(exc, retries))
                    retries += 1
                    continue
                raise exc

            return self._handle_response(response, model=model, text=text)

    # ------------------------------------------------------------------ #
    # Auth (SPEC §11.1)
    # ------------------------------------------------------------------ #
    async def login(self, username: str, password: str) -> AuthResult:
        result = await self._request(
            "POST",
            "/api/v1/auth/login",
            auth="none",
            json={"username": username, "password": password},
            model=AuthResult,
        )
        self._store_tokens(result)
        return result

    async def refresh_token(self) -> RefreshTokenResult:
        async with self._refresh_lock:
            if not self._refresh_token:
                raise AuthenticationError(
                    status_code=401,
                    code="invalid_token",
                    message="No refresh token available",
                    response=_NO_RESPONSE,
                )
            return await self._do_refresh()

    async def logout(self) -> None:
        await self._request(
            "POST",
            "/api/v1/auth/logout",
            auth="jwt",
            model=_MessageResponse,
        )
        self._clear_tokens()

    async def change_password(self, current: str, new: str) -> str:
        result = await self._request(
            "POST",
            "/api/v1/auth/change-password",
            auth="jwt",
            json={"current_password": current, "new_password": new},
            model=_MessageResponse,
        )
        return result.message

    async def get_post_key(self) -> str:
        result = await self._request(
            "GET",
            "/api/v1/post-key",
            auth="jwt",
            model=PostKeyResult,
        )
        self._post_key = result.post_key
        return result.post_key

    # ------------------------------------------------------------------ #
    # Posts (SPEC §11.2)
    # ------------------------------------------------------------------ #
    async def create_post(self, title: str, body: str, post_key: str | None = None) -> PostCreated:
        key = post_key or self._post_key
        if not key:
            key = await self.get_post_key()
        return await self._request(
            "POST",
            f"/{key}",
            auth="post_key",
            json={"title": title, "body": body},
            model=PostCreated,
        )

    async def get_post(
        self,
        qid: str,
        format: str = "html",
        if_none_match: str | None = None,
    ) -> str | None:
        params: dict[str, str] = {}
        if format == "raw":
            params["format"] = "raw"
        headers: dict[str, str] | None = None
        if if_none_match is not None:
            headers = {"If-None-Match": if_none_match}
        return await self._request(
            "GET",
            f"/{qid}",
            auth="none",
            params=params or None,
            model=None,
            text=True,
            extra_headers=headers,
            allow_304=if_none_match is not None,
        )

    async def list_posts(self, page: int = 1, limit: int = 20) -> Page[PostListItem]:
        return await self._request(
            "GET",
            "/api/v1/posts",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[PostListItem],
        )

    async def delete_post(self, qid: str) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/posts/{qid}",
            auth="jwt",
            model=None,
        )

    # ------------------------------------------------------------------ #
    # Delivery (SPEC §11.3)
    # ------------------------------------------------------------------ #
    async def list_channels(self) -> list[Channel]:
        data = await self._request(
            "GET",
            "/api/v1/delivery/channels",
            auth="jwt",
            model=_ItemsList[Channel],
        )
        return data.items

    async def create_channel(
        self,
        kind: str,
        name: str,
        configuration: dict[str, Any],
        keywords: str = "",
    ) -> Channel:
        data = await self._request(
            "POST",
            "/api/v1/delivery/channels",
            auth="jwt",
            json={
                "kind": kind,
                "name": name,
                "configuration": configuration,
                "keywords": keywords,
            },
            model=_ChannelWrapper,
        )
        return data.channel

    async def update_channel(self, id: int, **fields: Any) -> Channel:
        data = await self._request(
            "PATCH",
            f"/api/v1/delivery/channels/{id}",
            auth="jwt",
            json=fields if fields else None,
            model=_ChannelWrapper,
        )
        return data.channel

    async def delete_channel(self, id: int) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/delivery/channels/{id}",
            auth="jwt",
            model=None,
        )

    async def test_channel(self, id: int) -> str:
        """Send a diagnostic test message to a channel's webhook.

        Fire-and-forget on the backend side: it does NOT enter the retry queue
        and writes no ``delivery_history`` row. Returns the backend's
        confirmation message (``"test message sent"``).
        """
        result = await self._request(
            "POST",
            f"/api/v1/delivery/channels/{id}/test",
            auth="jwt",
            model=_MessageResponse,
        )
        return result.message

    async def list_delivery_history(
        self,
        channel_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> Page[DeliveryHistoryItem]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if channel_id is not None:
            params["channel_id"] = channel_id
        return await self._request(
            "GET",
            "/api/v1/delivery/history",
            auth="jwt",
            params=params,
            model=Page[DeliveryHistoryItem],
        )

    async def list_latest_delivery(self) -> list[DeliveryHistoryItem]:
        """List the most recent delivery per channel for the current user.

        Returns one item per channel that has any history (channels with no
        deliveries are absent). No pagination — a bare list, like
        :meth:`list_channels`.
        """
        data = await self._request(
            "GET",
            "/api/v1/delivery/latest",
            auth="jwt",
            model=_ItemsList[DeliveryHistoryItem],
        )
        return data.items

    # ------------------------------------------------------------------ #
    # Admin (SPEC §11.4)
    # ------------------------------------------------------------------ #
    async def admin_list_users(self, page: int = 1, limit: int = 20) -> Page[AdminUser]:
        return await self._request(
            "GET",
            "/api/v1/admin/users",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[AdminUser],
        )

    async def admin_list_posts(
        self, search: str = "", page: int = 1, limit: int = 20
    ) -> Page[AdminPost]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if search:
            params["search"] = search
        return await self._request(
            "GET",
            "/api/v1/admin/posts",
            auth="jwt",
            params=params,
            model=Page[AdminPost],
        )

    async def admin_delete_post(self, qid: str) -> None:
        await self._request(
            "DELETE",
            f"/api/v1/admin/posts/{qid}",
            auth="jwt",
            model=None,
        )

    async def admin_list_channels(self, page: int = 1, limit: int = 20) -> Page[AdminChannel]:
        return await self._request(
            "GET",
            "/api/v1/admin/delivery/channels",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[AdminChannel],
        )

    async def admin_list_delivery_history(
        self, page: int = 1, limit: int = 20
    ) -> Page[DeliveryHistoryItem]:
        return await self._request(
            "GET",
            "/api/v1/admin/delivery/history",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[DeliveryHistoryItem],
        )

    # ------------------------------------------------------------------ #
    # Health (SPEC §11.5)
    # ------------------------------------------------------------------ #
    async def health(self) -> str:
        data = await self._request(
            "GET",
            "/api/v1/health",
            auth="none",
            model=_StatusResponse,
        )
        return data.status


# Stand-in response for errors raised before any request was sent.
_NO_RESPONSE = httpx.Response(status_code=401, text="")
