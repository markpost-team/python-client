"""Shared logic for the sync and async Markpost clients.

Everything that does not depend on whether a call blocks lives here, so the
sync (``_sync.py``) and async (``_async.py``) subclasses only differ on four
operations (SPEC §3.1):

    - sending an HTTP request        (send vs await send)
    - sleeping for retry backoff     (time.sleep vs anyio.sleep)
    - the single-flight refresh lock (threading.Lock vs asyncio.Lock)
    - closing the http client        (close vs aclose)

The actual ``_request`` pipeline (build → send → handle → retry) is implemented
per subclass because the ``await`` points differ, but it delegates the
non-blocking steps to helpers in this base class.
"""

from __future__ import annotations

import random
import time
from typing import (
    Any,
    Generic,
    Literal,
    TypeVar,
)

import httpx
from pydantic import TypeAdapter

from ._constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
    TOKEN_REFRESH_MARGIN,
)
from ._exceptions import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from ._models import AuthResult


def _adapter_for(model: Any) -> TypeAdapter[Any]:
    """Return a (cached) ``TypeAdapter`` for a model or parametrized generic.

    ``TypeAdapter`` does non-trivial work at construction time, so we memoize by
    the model key to keep request parsing cheap across calls.
    """
    cached = _ADAPTER_CACHE.get(model)
    if cached is None:
        cached = TypeAdapter(model)
        _ADAPTER_CACHE[model] = cached
    return cached


_ADAPTER_CACHE: dict[Any, TypeAdapter[Any]] = {}

_HttpxClientT = TypeVar("_HttpxClientT", httpx.Client, httpx.AsyncClient)

AuthMode = Literal["jwt", "post_key", "none"]


class _BaseClient(Generic[_HttpxClientT]):
    """Generic base carrying token state and all sync/async-agnostic helpers.

    The type parameter ``_HttpxClientT`` is ``httpx.Client`` for the sync
    client and ``httpx.AsyncClient`` for the async client.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        post_key: str | None = None,
        http_client: _HttpxClientT | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        self._base_url = base_url.rstrip("/")
        # An explicit http_client wins; otherwise build one (subclass hook).
        self._http: _HttpxClientT = (
            http_client
            if http_client is not None
            else self._make_http(timeout if timeout is not None else DEFAULT_TIMEOUT)
        )
        self.max_retries = max_retries
        # Token state — shared between proactive and reactive single-flight refresh.
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expires_at: float = 0.0  # monotonic baseline
        self._post_key: str | None = post_key
        # Instantiated by the subclass with the right lock type.
        self._refresh_lock: Any = None
        # Bumped on every successful refresh; used to dedupe concurrent
        # reactive (401-triggered) refreshes: a 401 that observes the token
        # already changed since it was sent does not need to refresh again.
        self._refresh_generation: int = 0

    # ------------------------------------------------------------------ #
    # Subclass hooks (the only blocking operations)
    # ------------------------------------------------------------------ #
    def _make_http(self, timeout: float | httpx.Timeout) -> _HttpxClientT:
        raise NotImplementedError

    def _sleep(self, seconds: float) -> Any:
        raise NotImplementedError

    def _send(self, request: httpx.Request) -> Any:
        raise NotImplementedError

    def _refresh_if_needed(self) -> Any:
        """Preflight single-flight refresh hook (sync returns bool, async coroutine).

        Implementations should refresh only when the token is near expiry.
        """
        raise NotImplementedError

    def _force_refresh(self, stale_generation: int) -> Any:
        """Reactive single-flight refresh hook, triggered by a 401.

        ``stale_generation`` is the token generation observed when the 401 was
        received. Implementations must refresh if the generation is still current
        (i.e. nobody else has refreshed yet), and return True if the token is now
        newer than ``stale_generation``.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # URL & header construction (M2-2)
    # ------------------------------------------------------------------ #
    def _build_url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _auth_headers(self) -> dict[str, str]:
        if self._access_token:
            return {"Authorization": f"Bearer {self._access_token}"}
        return {}

    # ------------------------------------------------------------------ #
    # Request construction (M2-3)
    # ------------------------------------------------------------------ #
    def _build_request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: Any | None = None,
        auth: AuthMode = "jwt",
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Request:
        """Build an ``httpx.Request`` with auth headers injected per ``auth`` mode.

        - ``jwt``:      inject the ``Authorization: Bearer <token>`` header (if present).
        - ``post_key``/``none``: no JWT.
        """
        headers: dict[str, str] = {}
        if auth == "jwt":
            headers.update(self._auth_headers())
        if extra_headers:
            headers.update(extra_headers)
        return self._http.build_request(
            method,
            self._build_url(path),
            json=json,
            params=params,
            headers=headers,
        )

    # ------------------------------------------------------------------ #
    # Response handling (M2-4 / M2-5)
    # ------------------------------------------------------------------ #
    def _handle_response(self, response: httpx.Response, *, model: Any, text: bool = False) -> Any:
        """Parse a 2xx response.

        - ``text=True``:    return the raw body string (get_post html/markdown),
                            regardless of ``model``.
        - ``model is None``: return ``None`` (e.g. a 204 with no body).
        - otherwise:        parse JSON and validate via a ``TypeAdapter`` built
                            for ``model``. ``TypeAdapter`` handles both plain
                            models and runtime-parametrized generics like
                            ``Page[PostListItem]`` or ``_ItemsList[Channel]``.
        """
        if text:
            return response.text
        if model is None:
            return None
        data = response.json()
        adapter = _adapter_for(model)
        return adapter.validate_python(data)

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Map a non-2xx response to the most specific ``APIError`` subclass."""
        if 200 <= response.status_code < 300:
            return
        raise APIError.from_response(response)

    # ------------------------------------------------------------------ #
    # Retry strategy (M2-6) — non-blocking
    # ------------------------------------------------------------------ #
    def _should_retry(self, exc: BaseException) -> bool:
        """Only transient failures are retried (SPEC §9.1)."""
        if isinstance(exc, (APITimeoutError, APIConnectionError)):
            return True
        if isinstance(exc, InternalServerError):
            return True
        if isinstance(exc, RateLimitError):
            return True
        return False

    def _calculate_retry_delay(self, exc: BaseException, retries_taken: int) -> float:
        """Exponential backoff with jitter (SPEC §9.2).

        If the backend gave a ``RateLimit-Reset`` and it's within (0, 60]s, honor
        it directly; otherwise ``min(BASE * 2**n, MAX)`` scaled by 0.75–1.0 jitter.
        """
        if isinstance(exc, RateLimitError) and exc.reset is not None:
            if 0 < exc.reset <= TOKEN_REFRESH_MARGIN:
                return float(exc.reset)
        delay = min(RETRY_BASE_DELAY * (2**retries_taken), RETRY_MAX_DELAY)
        # Jitter: multiply by a factor in [0.75, 1.0).
        delay *= 1 - 0.25 * random.random()
        return delay

    # ------------------------------------------------------------------ #
    # Token state (M2-7)
    # ------------------------------------------------------------------ #
    def _is_token_expiring(self) -> bool:
        """True if the access token will expire within ``TOKEN_REFRESH_MARGIN``."""
        return time.monotonic() > self._token_expires_at - TOKEN_REFRESH_MARGIN

    def _store_tokens(self, result: AuthResult) -> None:
        """Persist tokens from an auth result and record the expiry deadline."""
        self._access_token = result.token
        self._refresh_token = result.refresh_token
        self._token_expires_at = time.monotonic() + result.expires_in
        self._refresh_generation += 1

    def _store_refresh(self, result: Any) -> None:
        """Persist tokens from a refresh result (no ``user`` field).

        ``result`` is a :class:`RefreshTokenResult`; typed loosely here to avoid
        an import cycle (it carries ``token``/``refresh_token``/``expires_in``).
        """
        self._access_token = result.token
        self._refresh_token = result.refresh_token
        self._token_expires_at = time.monotonic() + result.expires_in
        self._refresh_generation += 1

    def _clear_tokens(self) -> None:
        """Drop all local token state (used after ``logout``)."""
        self._access_token = None
        self._refresh_token = None
        self._token_expires_at = 0.0
