"""Synchronous Markpost client.

Implements the full request pipeline (build → preflight refresh → send →
handle → retry) and every public resource method listed in SPEC §11.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

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

__all__ = ["Markpost"]

_CFG = ConfigDict(extra="ignore")
_T = TypeVar("_T")


# --- internal response wrappers for endpoints that nest under a key -------------


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


class Markpost(_BaseClient[httpx.Client]):
    """Synchronous client for the Markpost API.

    Example::

        with Markpost("https://markpost.cc", username, password) as client:
            created = client.create_post("Hello", "# body")

    Args:
        base_url: Backend origin, e.g. ``"https://markpost.cc"``.
        username: Optional username. When given with ``password``, the client
            logs in immediately on construction.
        password: Optional password (paired with ``username``).
        timeout: Per-request timeout (seconds or ``httpx.Timeout``). Defaults to
            a safe connect/read/write/pool split.
        max_retries: How many times to retry a transient failure. ``0`` disables.
        post_key: Pre-seed a post key so ``create_post`` need not fetch one.
        http_client: Inject a custom ``httpx.Client`` (mainly for tests).
        verify: Whether to verify TLS certificates. Set ``False`` for the
            self-signed container used in e2e tests.
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
        http_client: httpx.Client | None = None,
        verify: bool = True,
    ) -> None:
        # Stash flags before super().__init__ (which may call _make_http).
        self._verify = verify
        super().__init__(
            base_url,
            timeout=timeout,
            max_retries=max_retries,
            post_key=post_key,
            http_client=http_client,
        )
        self._refresh_lock = threading.Lock()
        # Auto-login when credentials are provided (SPEC §10.2).
        if username and password:
            self.login(username, password)

    # ------------------------------------------------------------------ #
    # Subclass hooks (the blocking operations — SPEC §3.1)
    # ------------------------------------------------------------------ #
    def _make_http(self, timeout: float | httpx.Timeout) -> httpx.Client:
        return httpx.Client(timeout=timeout, verify=self._verify)

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)

    def _send(self, request: httpx.Request) -> httpx.Response:
        return self._http.send(request)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    def __enter__(self) -> Markpost:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Single-flight refresh (M4)
    # ------------------------------------------------------------------ #
    def _refresh_if_needed(self) -> bool:
        """Single-flight refresh: at most one in-flight refresh at a time.

        Double-checked locking means concurrent callers that arrive while a
        refresh is in progress simply observe the already-refreshed token.
        Returns ``True`` if there is now a usable (non-expiring) access token,
        ``False`` if a refresh was attempted but failed.
        """
        with self._refresh_lock:
            # Fast path: another caller already refreshed to a fresh token.
            if self._access_token and not self._is_token_expiring():
                return True
            if not self._refresh_token:
                return False
            try:
                self._do_refresh()
                return True
            except Exception:
                return False

    def _force_refresh(self, stale_generation: int) -> bool:
        """Reactive single-flight refresh, triggered when a 401 is received.

        ``stale_generation`` is the token generation observed when the 401
        arrived. We only perform a refresh if the token has NOT been rotated
        since (double-checked against concurrent refreshers). Returns True if
        the token is now newer than ``stale_generation`` (whether or not this
        call did the work), False if a refresh was attempted and failed.
        """
        with self._refresh_lock:
            if self._refresh_generation != stale_generation:
                # Some other caller already refreshed past the stale token.
                return True
            if not self._refresh_token:
                return False
            try:
                self._do_refresh()
                return True
            except Exception:
                return False

    def _do_refresh(self) -> RefreshTokenResult:
        """Call ``/auth/refresh`` directly, bypassing ``_request``'s 401 handling.

        Going through ``_request`` here would re-enter the lock and/or the 401
        retry path (SPEC R3 — async deadlock; same hazard for sync). We talk to
        ``self._http`` directly instead. Parses the backend's
        ``RefreshTokenResponse`` (no ``user`` field) and stores the new pair.
        """
        request = self._build_request(
            "POST",
            "/api/v1/auth/refresh",
            json={"refresh_token": self._refresh_token},
            auth="none",
        )
        response = self._send(request)
        self._raise_for_status(response)
        result = RefreshTokenResult.model_validate(response.json())
        self._store_refresh(result)
        return result

    # ------------------------------------------------------------------ #
    # Request pipeline (M3-2)
    # ------------------------------------------------------------------ #
    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: AuthMode = "jwt",
        json: Any | None = None,
        params: Any | None = None,
        model: type[Any] | None = None,
        text: bool = False,
        extra_headers: dict[str, str] | None = None,
        allow_304: bool = False,
    ) -> Any:
        # Preflight: if this request needs a JWT and the token is about to
        # expire, single-flight refresh BEFORE sending (SPEC §4.2 trigger #1).
        # create_post uses post_key auth, so it is correctly skipped here.
        if auth == "jwt" and self._access_token and self._is_token_expiring():
            self._refresh_if_needed()

        retries = 0
        retried_401 = False
        while True:
            # Capture the token generation we are sending WITH, so a later 401
            # can tell whether the token was already rotated by another caller.
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
                response = self._send(request)
            except httpx.TimeoutException as e:
                exc: APIError = cast("APIError", APIError._timeout(str(e) or "Request timed out"))
                if retries < self.max_retries and self._should_retry(exc):
                    self._sleep(self._calculate_retry_delay(exc, retries))
                    retries += 1
                    continue
                raise exc from e
            except httpx.TransportError as e:
                exc = cast("APIError", APIError._connection(str(e) or "Connection error"))
                if retries < self.max_retries and self._should_retry(exc):
                    self._sleep(self._calculate_retry_delay(exc, retries))
                    retries += 1
                    continue
                raise exc from e

            # Conditional GET: backend returned 304 -> nothing changed.
            if allow_304 and response.status_code == 304:
                return None

            # Reactive single-flight: a 401 on a JWT request triggers ONE
            # forced refresh and ONE retry (guarded by ``retried_401``). The
            # generation guard prevents concurrent 401s from each refreshing.
            if (
                response.status_code == 401
                and auth == "jwt"
                and self._refresh_token
                and not retried_401
            ):
                retried_401 = True
                if self._force_refresh(sent_generation):
                    continue
                # Refresh failed -> fall through and raise AuthenticationError.

            if not (200 <= response.status_code < 300):
                exc = APIError.from_response(response)
                if retries < self.max_retries and self._should_retry(exc):
                    self._sleep(self._calculate_retry_delay(exc, retries))
                    retries += 1
                    continue
                raise exc

            return self._handle_response(response, model=model, text=text)

    # ------------------------------------------------------------------ #
    # Auth (SPEC §11.1)
    # ------------------------------------------------------------------ #
    def login(self, username: str, password: str) -> AuthResult:
        result = self._request(
            "POST",
            "/api/v1/auth/login",
            auth="none",
            json={"username": username, "password": password},
            model=AuthResult,
        )
        self._store_tokens(result)
        return result

    def refresh_token(self) -> RefreshTokenResult:
        """Explicitly refresh the access token.

        Under the hood this is the same single-flight path used automatically on
        expiry / 401, so concurrent explicit refreshes collapse into one backend
        call (backend refresh tokens are one-time-rotated; reuse is detected).

        Returns the backend's ``RefreshTokenResponse`` (token pair only — no
        ``user``, since the backend does not return one on refresh).
        """
        with self._refresh_lock:
            if not self._refresh_token:
                raise AuthenticationError(
                    status_code=401,
                    code="invalid_token",
                    message="No refresh token available",
                    response=_NO_RESPONSE,
                )
            return self._do_refresh()

    def logout(self) -> None:
        # Body is {"message": str} but callers want the side-effect (tokens
        # cleared). We still validate the body to surface backend errors.
        self._request(
            "POST",
            "/api/v1/auth/logout",
            auth="jwt",
            model=_MessageResponse,
        )
        self._clear_tokens()

    def change_password(self, current: str, new: str) -> str:
        result = self._request(
            "POST",
            "/api/v1/auth/change-password",
            auth="jwt",
            json={"current_password": current, "new_password": new},
            model=_MessageResponse,
        )
        return result.message

    def get_post_key(self) -> str:
        result = self._request(
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
    def create_post(self, title: str, body: str, post_key: str | None = None) -> PostCreated:
        key = post_key or self._post_key
        if not key:
            # Auto-fetch + cache (SPEC §6.2).
            key = self.get_post_key()
        # Root-level path; post_key auth (NO JWT) — main.go:460.
        return self._request(
            "POST",
            f"/{key}",
            auth="post_key",
            json={"title": title, "body": body},
            model=PostCreated,
        )

    def get_post(
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
        # Public, root-level GET (main.go:463). Returns text; 304 -> None.
        return self._request(
            "GET",
            f"/{qid}",
            auth="none",
            params=params or None,
            model=None,
            text=True,
            extra_headers=headers,
            allow_304=if_none_match is not None,
        )

    def list_posts(self, page: int = 1, limit: int = 20) -> Page[PostListItem]:
        return self._request(
            "GET",
            "/api/v1/posts",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[PostListItem],
        )

    def delete_post(self, qid: str) -> None:
        self._request(
            "DELETE",
            f"/api/v1/posts/{qid}",
            auth="jwt",
            model=None,
        )

    # ------------------------------------------------------------------ #
    # Delivery (SPEC §11.3)
    # ------------------------------------------------------------------ #
    def list_channels(self) -> list[Channel]:
        # No pagination — types.go:151 ChannelsListResponse is {items:[...]}.
        data = self._request(
            "GET",
            "/api/v1/delivery/channels",
            auth="jwt",
            model=_ItemsList[Channel],
        )
        return data.items

    def create_channel(
        self,
        kind: str,
        name: str,
        configuration: dict[str, Any],
        keywords: str = "",
    ) -> Channel:
        data = self._request(
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

    def update_channel(self, id: int, **fields: Any) -> Channel:
        # PATCH semantics: only send the fields the caller passed. Omitting all
        # fields still PATCHes an empty object (no-op, allowed by backend).
        data = self._request(
            "PATCH",
            f"/api/v1/delivery/channels/{id}",
            auth="jwt",
            json=fields if fields else None,
            model=_ChannelWrapper,
        )
        return data.channel

    def delete_channel(self, id: int) -> None:
        self._request(
            "DELETE",
            f"/api/v1/delivery/channels/{id}",
            auth="jwt",
            model=None,
        )

    def test_channel(self, id: int) -> str:
        """Send a diagnostic test message to a channel's webhook.

        Fire-and-forget on the backend side: it does NOT enter the retry queue
        and writes no ``delivery_history`` row. Returns the backend's
        confirmation message (``"test message sent"``).
        """
        result = self._request(
            "POST",
            f"/api/v1/delivery/channels/{id}/test",
            auth="jwt",
            model=_MessageResponse,
        )
        return result.message

    def list_delivery_history(
        self,
        channel_id: int | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> Page[DeliveryHistoryItem]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if channel_id is not None:
            params["channel_id"] = channel_id
        return self._request(
            "GET",
            "/api/v1/delivery/history",
            auth="jwt",
            params=params,
            model=Page[DeliveryHistoryItem],
        )

    def list_latest_delivery(self) -> list[DeliveryHistoryItem]:
        """List the most recent delivery per channel for the current user.

        Returns one item per channel that has any history (channels with no
        deliveries are absent). No pagination — a bare list, like
        :meth:`list_channels`.
        """
        data = self._request(
            "GET",
            "/api/v1/delivery/latest",
            auth="jwt",
            model=_ItemsList[DeliveryHistoryItem],
        )
        return data.items

    # ------------------------------------------------------------------ #
    # Admin (SPEC §11.4)
    # ------------------------------------------------------------------ #
    def admin_list_users(self, page: int = 1, limit: int = 20) -> Page[AdminUser]:
        return self._request(
            "GET",
            "/api/v1/admin/users",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[AdminUser],
        )

    def admin_list_posts(self, search: str = "", page: int = 1, limit: int = 20) -> Page[AdminPost]:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if search:
            params["search"] = search
        return self._request(
            "GET",
            "/api/v1/admin/posts",
            auth="jwt",
            params=params,
            model=Page[AdminPost],
        )

    def admin_delete_post(self, qid: str) -> None:
        self._request(
            "DELETE",
            f"/api/v1/admin/posts/{qid}",
            auth="jwt",
            model=None,
        )

    def admin_list_channels(self, page: int = 1, limit: int = 20) -> Page[AdminChannel]:
        return self._request(
            "GET",
            "/api/v1/admin/delivery/channels",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[AdminChannel],
        )

    def admin_list_delivery_history(
        self, page: int = 1, limit: int = 20
    ) -> Page[DeliveryHistoryItem]:
        return self._request(
            "GET",
            "/api/v1/admin/delivery/history",
            auth="jwt",
            params={"page": page, "limit": limit},
            model=Page[DeliveryHistoryItem],
        )

    # ------------------------------------------------------------------ #
    # Health (SPEC §11.5)
    # ------------------------------------------------------------------ #
    def health(self) -> str:
        data = self._request(
            "GET",
            "/api/v1/health",
            auth="none",
            model=_StatusResponse,
        )
        return data.status


# A response stand-in used when raising an APIError without a real httpx.Response
# (e.g. "no refresh token available" before any request was sent). Carries the
# status code the error logically belongs to.
_NO_RESPONSE = httpx.Response(status_code=401, text="")
