English | [简体中文](README_zh.md)

<div align="center">

# Markpost Python Client

**A typed, sync + async Python client for the [Markpost](https://markpost.cc) API.**

[![PyPI version](https://img.shields.io/pypi/v/markpost.svg)](https://pypi.org/project/markpost/)
[![Python versions](https://img.shields.io/pypi/pyversions/markpost.svg)](https://pypi.org/project/markpost/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE.txt)
[![CI](https://img.shields.io/github/actions/workflow/status/markpost-team/python-client/ci.yml?label=CI)](https://github.com/markpost-team/python-client/actions/workflows/ci.yml)

</div>

---

## Installation

> Requires Python **>=3.10**.

```bash
uv add markpost
# or
pip install markpost
```

## Quick Start

### Sync

```python
from markpost import Markpost

with Markpost("https://markpost.cc", "alice", "secret") as client:
    created = client.create_post("Hello", "# Body in **markdown**")
    print(created.id)           # "p-<nanoid>"

    html = client.get_post(created.id)               # full HTML page (str)
    md = client.get_post(created.id, format="raw")   # "# Hello\n\n..." (str)

    page = client.list_posts(limit=20)
    for item in page.items:
        print(item.qid, item.title)
```

### Async

```python
from markpost import AsyncMarkpost

async with AsyncMarkpost("https://markpost.cc", "alice", "secret") as client:
    created = await client.create_post("Hello", "# Body")
    html = await client.get_post(created.id)
    page = await client.list_posts(limit=20)
```

## Authentication

Pass `username` + `password` to the constructor to auto-login (sync logs in
immediately; async logs in lazily on the first call or `__aenter__`):

```python
client = Markpost("https://markpost.cc", username="alice", password="secret")
```

Or log in manually:

```python
client = Markpost("https://markpost.cc")
result = client.login("alice", "secret")
print(result.user.role, result.token)
```

The access token is refreshed **automatically** when it is about to expire or
when the backend returns `401`. Concurrent refreshes are deduplicated into a
single backend call (single-flight), which is essential because the backend
rotates refresh tokens one-time and revokes the whole session on reuse.

## Posts

`create_post` authenticates with a **post key** (not a JWT). If you don't pass
one, the client fetches and caches your post key automatically.

```python
created = client.create_post("Title", "body")               # auto-fetches post key
created = client.create_post("Title", "body", post_key="mpk-...")
```

`get_post` returns a `str` (HTML by default, or markdown when `format="raw"`).
It supports conditional requests via `If-None-Match`:

```python
etag = "...from a previous response..."
result = client.get_post("p-abc", if_none_match=etag)
# result is None when the backend returns 304 (not modified)
```

Pagination uses a flat structure:

```python
page = client.list_posts(page=2, limit=50)
# page.items, page.total, page.page, page.limit, page.total_pages
```

## Delivery channels & history

```python
ch = client.create_channel(
    kind="feishu",
    name="ops-alerts",
    configuration={"webhook_url": "https://...", "card_link_url": "https://..."},
    keywords="",  # optional keyword filter expression
)

# PATCH semantics: pass only the fields you want to change.
client.update_channel(ch.id, enabled=False)

channels = client.list_channels()          # list[Channel] (no pagination)
history = client.list_delivery_history(channel_id=ch.id)  # Page[DeliveryHistoryItem]
latest = client.list_latest_delivery()     # list[DeliveryHistoryItem], one per channel

# Send a diagnostic card to verify the webhook is wired up. Fire-and-forget:
# the backend sends it synchronously but writes no delivery_history row.
client.test_channel(ch.id)
```

## Error handling

Errors are a typed hierarchy rooted at `MarkpostError`:

```python
from markpost import (
    MarkpostError, APIError,
    BadRequestError, AuthenticationError, PermissionDeniedError,
    NotFoundError, ConflictError, UnprocessableEntityError, RateLimitError,
    InternalServerError, APITimeoutError, APIConnectionError,
)

try:
    client.create_post("", "body")
except UnprocessableEntityError as e:
    print(e.status_code, e.code)   # 422 "title_too_long" / "required" / ...
    for fe in e.errors:            # parsed per-field details
        print(fe.field, fe.code, fe.message)
except RateLimitError as e:
    print(e.limit, e.remaining, e.reset)   # parsed from RateLimit-* headers
except AuthenticationError as e:
    print(e.code)                  # "invalid_credentials", "invalid_token", ...
except APIError as e:
    print(e.status_code, e.code, e.message)
```

Timeouts and network errors map to `APITimeoutError` / `APIConnectionError`
(both retried automatically). `5xx` and `429` are retried; `4xx` are not.

## Configuration

```python
Markpost(
    base_url,
    username=None,
    password=None,
    *,
    timeout=None,             # float | httpx.Timeout (defaults to a safe connect/read/write/pool split)
    max_retries=2,             # 0 disables retries
    post_key=None,             # pre-seed a post key
    http_client=None,          # inject a custom httpx client (testing)
    verify=True,               # set False for the self-signed e2e container
)
```

## License

MIT License — see [LICENSE.txt](LICENSE.txt).
