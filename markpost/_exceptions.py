"""Exception hierarchy for the Markpost SDK.

Layout (SPEC §8)::

    MarkpostError                              (root)
    ├── APIError                               (backend returned an error response)
    │   ├── BadRequestError            (400)
    │   ├── AuthenticationError        (401)
    │   ├── PermissionDeniedError      (403)
    │   ├── NotFoundError              (404)
    │   ├── ConflictError              (409)
    │   ├── UnprocessableEntityError   (422)   # carries errors[] detail
    │   ├── RateLimitError             (429)   # parses rate-limit headers
    │   └── InternalServerError        (>=500)
    ├── APITimeoutError                         (httpx TimeoutException)
    └── APIConnectionError                      (httpx network error)
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict


class MarkpostError(Exception):
    """Root type for every error raised by this SDK."""


class APIError(MarkpostError):
    """Raised when the backend returns a non-2xx response.

    Attributes:
        status_code: The HTTP status code returned by the backend.
        code: Backend machine-readable error code (e.g. ``"invalid_credentials"``),
            or ``None`` if the body had no ``code`` field.
        message: Human-readable message from the backend body, falling back to
            the raw response text.
        response: The original ``httpx.Response``.
        body: The parsed response body (``dict``) if it was JSON, else ``None``.
    """

    def __init__(
        self,
        *,
        status_code: int,
        code: str | None,
        message: str,
        response: httpx.Response,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.response = response
        self.body = body
        super().__init__(f"{status_code} {code or 'Error'}: {message}")

    @classmethod
    def from_response(
        cls,
        response: httpx.Response,
        *,
        message: str | None = None,
        code: str | None = None,
    ) -> APIError:
        """Build the most specific ``APIError`` subclass for a response.

        Used by ``_BaseClient._raise_for_status``. Parses the JSON body to pull
        ``code``/``message`` when present and, for 422/429, the extra detail
        fields defined in SPEC §8.2/§8.3.
        """
        try:
            body: dict[str, Any] | None = response.json()
        except Exception:
            body = None

        if isinstance(body, dict):
            code = code if code is not None else body.get("code")
            if message is None:
                message = body.get("message") or ""
        elif message is None:
            message = ""

        if not message:
            message = response.text or ""

        status = response.status_code
        exc_cls = _status_to_exception(status)

        if exc_cls is UnprocessableEntityError:
            errors = []
            if isinstance(body, dict):
                raw_errors = body.get("errors")
                if isinstance(raw_errors, list):
                    for item in raw_errors:
                        if isinstance(item, dict):
                            try:
                                errors.append(FieldError.model_validate(item))
                            except Exception:
                                errors.append(
                                    FieldError(
                                        field=item.get("field"),
                                        code=str(item.get("code", "")),
                                        message=str(item.get("message", "")),
                                    )
                                )
            return UnprocessableEntityError(
                status_code=status,
                code=code,
                message=message,
                response=response,
                body=body,
                errors=errors,
            )

        if exc_cls is RateLimitError:
            limit = _parse_int_header(response, "ratelimit-limit")
            remaining = _parse_int_header(response, "ratelimit-remaining")
            reset = _parse_float_header(response, "ratelimit-reset")
            return RateLimitError(
                status_code=status,
                code=code,
                message=message,
                response=response,
                body=body,
                limit=limit,
                remaining=remaining,
                reset=reset,
            )

        return exc_cls(
            status_code=status,
            code=code,
            message=message,
            response=response,
            body=body,
        )

    @staticmethod
    def _timeout(message: str) -> APITimeoutError:
        """Construct an :class:`APITimeoutError` from an httpx timeout message."""
        return APITimeoutError(message)

    @staticmethod
    def _connection(message: str) -> APIConnectionError:
        """Construct an :class:`APIConnectionError` from an httpx transport message."""
        return APIConnectionError(message)


class BadRequestError(APIError):
    """400 — the request itself is malformed."""


class AuthenticationError(APIError):
    """401 — credentials missing, invalid, or token refresh failed."""


class PermissionDeniedError(APIError):
    """403 — authenticated but not allowed (e.g. non-admin hitting admin route)."""


class NotFoundError(APIError):
    """404 — resource does not exist."""


class ConflictError(APIError):
    """409 — conflicting state (e.g. duplicate resource)."""


class FieldError(BaseModel):
    """A single validation error item from a 422 response (SPEC §8.2).

    Backend shape: ``{"field": str (optional), "code": str, "message": str}``.
    """

    model_config = ConfigDict(extra="ignore")

    field: str | None = None
    code: str
    message: str


class UnprocessableEntityError(APIError):
    """422 — validation failure. Carries per-field ``errors[]`` detail."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str | None,
        message: str,
        response: httpx.Response,
        body: dict[str, Any] | None = None,
        errors: list[FieldError] | None = None,
    ) -> None:
        self.errors = errors or []
        super().__init__(
            status_code=status_code,
            code=code,
            message=message,
            response=response,
            body=body,
        )


class RateLimitError(APIError):
    """429 — rate limited. Carries the parsed ``RateLimit-*`` headers."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str | None,
        message: str,
        response: httpx.Response,
        body: dict[str, Any] | None = None,
        limit: int | None = None,
        remaining: int | None = None,
        reset: float | None = None,
    ) -> None:
        self.limit = limit
        self.remaining = remaining
        self.reset = reset
        super().__init__(
            status_code=status_code,
            code=code,
            message=message,
            response=response,
            body=body,
        )


class InternalServerError(APIError):
    """>=500 — backend fault. Retriable."""


class APITimeoutError(MarkpostError):
    """The request timed out (httpx ``TimeoutException``). Retriable."""

    def __init__(self, message: str = "Request timed out") -> None:
        self.message = message
        super().__init__(message)


class APIConnectionError(MarkpostError):
    """A network/transport error occurred before a response was received. Retriable."""

    def __init__(self, message: str = "Connection error") -> None:
        self.message = message
        super().__init__(message)


def _status_to_exception(status_code: int) -> type[APIError]:
    """Map an HTTP status code to its exception class (SPEC §8.4).

    Unknown codes fall back to ``InternalServerError`` per the spec.
    """
    return _STATUS_TO_EXCEPTION.get(status_code, InternalServerError)


_STATUS_TO_EXCEPTION: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
}


def _parse_int_header(response: httpx.Response, name: str) -> int | None:
    """Read an optional response header as ``int`` (None if absent/invalid)."""
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_float_header(response: httpx.Response, name: str) -> float | None:
    """Read an optional response header as ``float`` (None if absent/invalid)."""
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
