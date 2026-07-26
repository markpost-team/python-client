"""Exception hierarchy & error mapping (TESTING §4.1)."""

from __future__ import annotations

import httpx
import pytest

from markpost import (
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
from markpost._exceptions import _status_to_exception

ALL_API_ERRORS = [
    BadRequestError,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    ConflictError,
    UnprocessableEntityError,
    RateLimitError,
    InternalServerError,
]


# U-E1: hierarchy ---------------------------------------------------------------
@pytest.mark.parametrize(
    "child,parent",
    [
        (APIError, MarkpostError),
        (APITimeoutError, MarkpostError),
        (APIConnectionError, MarkpostError),
        (BadRequestError, APIError),
        (AuthenticationError, APIError),
        (PermissionDeniedError, APIError),
        (NotFoundError, APIError),
        (ConflictError, APIError),
        (UnprocessableEntityError, APIError),
        (RateLimitError, APIError),
        (InternalServerError, APIError),
    ],
)
def test_exception_hierarchy(child, parent):
    assert issubclass(child, parent)
    assert issubclass(child, MarkpostError)


# U-E2: APIError fields ---------------------------------------------------------
def test_api_error_fields():
    resp = httpx.Response(404, json={"code": "not_found", "message": "missing"})
    err = APIError.from_response(resp)
    assert err.status_code == 404
    assert err.code == "not_found"
    assert err.message == "missing"
    assert err.response is resp
    assert err.body == {"code": "not_found", "message": "missing"}


# U-E3: 422 parses errors[] ----------------------------------------------------
def test_422_parses_field_errors():
    resp = httpx.Response(
        422,
        json={
            "code": "validation",
            "message": "invalid input",
            "errors": [
                {"field": "kind", "code": "required", "message": "kind is required"},
                {"code": "min_length", "message": "too short"},  # no field
            ],
        },
    )
    err = APIError.from_response(resp)
    assert isinstance(err, UnprocessableEntityError)
    assert len(err.errors) == 2
    assert isinstance(err.errors[0], FieldError)
    assert err.errors[0].field == "kind"
    assert err.errors[0].code == "required"
    assert err.errors[0].message == "kind is required"
    # field is omitempty on the backend -> None here
    assert err.errors[1].field is None
    assert err.errors[1].code == "min_length"


# U-E4: 429 parses rate-limit headers ------------------------------------------
def test_429_parses_ratelimit_headers():
    resp = httpx.Response(
        429,
        json={"code": "rate_limited", "message": "slow down"},
        headers={
            "RateLimit-Limit": "100",
            "RateLimit-Remaining": "0",
            "RateLimit-Reset": "12",
        },
    )
    err = APIError.from_response(resp)
    assert isinstance(err, RateLimitError)
    assert err.limit == 100
    assert err.remaining == 0
    assert err.reset == 12.0


def test_429_headers_missing_yield_none():
    resp = httpx.Response(429, json={"code": "rate_limited", "message": "slow"})
    err = APIError.from_response(resp)
    assert isinstance(err, RateLimitError)
    assert err.limit is None
    assert err.remaining is None
    assert err.reset is None


def test_429_header_garbage_yields_none():
    resp = httpx.Response(
        429,
        json={"code": "rate_limited", "message": "slow"},
        headers={"RateLimit-Reset": "not-a-number"},
    )
    err = APIError.from_response(resp)
    assert isinstance(err, RateLimitError)
    assert err.reset is None


# U-E5: status code -> exception mapping --------------------------------------
@pytest.mark.parametrize(
    "status,expected",
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, ConflictError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (500, InternalServerError),
        (502, InternalServerError),
        (503, InternalServerError),
        (599, InternalServerError),
        (418, InternalServerError),  # unknown -> InternalServerError
    ],
)
def test_status_code_mapping(status, expected):
    assert _status_to_exception(status) is expected
    resp = httpx.Response(status, json={"code": "x", "message": "y"})
    err = APIError.from_response(resp)
    assert isinstance(err, expected)


# U-E6: body is not JSON --------------------------------------------------------
def test_non_json_body_falls_back_to_text():
    resp = httpx.Response(500, text="boom: internal panic")
    err = APIError.from_response(resp)
    assert isinstance(err, InternalServerError)
    assert err.code is None
    assert err.body is None
    assert "boom" in err.message


# U-E7: body missing code field ------------------------------------------------
def test_body_without_code():
    resp = httpx.Response(500, json={})
    err = APIError.from_response(resp)
    assert isinstance(err, InternalServerError)
    assert err.code is None  # no crash
