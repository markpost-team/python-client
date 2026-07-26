# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0-rc.2] - 2026-07-26

First release candidate: a typed, sync + async Python client for the Markpost API.

### Added

- **Sync and async clients** — `Markpost` and `AsyncMarkpost` with identical
  signatures, so the same code pattern works in both threading and asyncio
  contexts.
- **Full type support** — `pydantic` v2 data models with a shipped `py.typed`
  marker (PEP 561), giving you IDE autocompletion and static type-checking.
- **Post management** — create, fetch (as rendered HTML or raw markdown), list,
  and delete posts, with `If-None-Match` conditional requests to save bandwidth
  on unchanged content.
- **Delivery channels** — create, update, and delete channels; send a test card
  to verify a webhook is wired up; query delivery history and the latest
  delivery per channel.
- **Admin endpoints** — list users, posts, channels, and delivery history
  (requires an admin-role account).
- **Authentication and sessions** — username/password auto-login, automatic
  access-token refresh before expiry, and single-flight refresh so concurrent
  401s collapse into one backend call.
- **Safe defaults** — every request enforces a timeout; network errors and
  server errors are retried automatically with jittered exponential backoff; the
  client honors `RateLimit-*` headers to avoid tripping 429s.
- **Clear error hierarchy** — a typed exception tree rooted at `MarkpostError`,
  with per-field details parsed out of 422 responses and rate-limit information
  parsed out of 429 responses.

### Changed

- Requires Python **>=3.10**.
- Built on `httpx` for the HTTP transport, providing a full async API.

[0.2.0-rc.2]: https://github.com/markpost-team/python-client/releases/tag/v0.2.0-rc.2
