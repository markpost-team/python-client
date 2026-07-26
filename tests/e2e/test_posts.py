"""E2E: posts full lifecycle (TESTING §5.4.3)."""

from __future__ import annotations

import pytest

from markpost import Markpost, NotFoundError, PermissionDeniedError, UnprocessableEntityError

pytestmark = pytest.mark.e2e

TITLE = "SDK e2e post"
BODY = "# Hello\n\nThis is a **test** body."


@pytest.fixture
def created_post(admin_client, base_url):
    """Create a post and return its qid; delete it after the test."""
    created = admin_client.create_post(TITLE, BODY)
    qid = created.id
    assert qid.startswith("p-")
    yield qid
    try:
        admin_client.delete_post(qid)
    except NotFoundError:
        pass


# E-P1 ------------------------------------------------------------------------
def test_create_and_get_html(admin_client, created_post):
    html = admin_client.get_post(created_post)
    assert isinstance(html, str)
    assert "<html" in html.lower() or TITLE in html


# E-P2 ------------------------------------------------------------------------
def test_create_and_get_raw(admin_client, created_post):
    md = admin_client.get_post(created_post, format="raw")
    assert isinstance(md, str)
    assert md.startswith("# ")
    assert BODY.split("\n")[0].lstrip("# ").strip() in md or "Hello" in md


# E-P3 ------------------------------------------------------------------------
def test_created_post_is_listed(admin_client, created_post):
    page = admin_client.list_posts(limit=100)
    qids = {item.qid for item in page.items}
    assert created_post in qids


# E-P4 ------------------------------------------------------------------------
def test_delete_post_then_404(admin_client, created_post):
    admin_client.delete_post(created_post)
    with pytest.raises(NotFoundError):
        admin_client.delete_post(created_post)


# E-P5 ------------------------------------------------------------------------
def test_delete_unknown_post_404(admin_client):
    with pytest.raises(NotFoundError):
        admin_client.delete_post("p-does-not-exist-zzz")


# E-P6 — real ETag conditional 304 -------------------------------------------
def test_etag_conditional_304(admin_client, created_post):
    # First fetch returns the body; httpx exposes the ETag header on the
    # underlying response via a raw GET through the http client.
    import httpx

    resp = httpx.get(f"http://localhost:2053/{created_post}", timeout=10.0)
    etag = resp.headers.get("ETag")
    assert etag, "backend should set an ETag"
    # Second fetch with If-None-Match -> SDK returns None (304).
    result = admin_client.get_post(created_post, if_none_match=etag)
    assert result is None


# E-P7 ------------------------------------------------------------------------
def test_pagination(base_url):
    with Markpost(base_url, "markpost", "markpost") as c:
        created_qids = []
        try:
            for i in range(25):
                created_qids.append(c.create_post(f"{TITLE} {i}", BODY).id)
            page = c.list_posts(page=1, limit=10)
            assert page.limit == 10
            assert len(page.items) == 10
            assert page.total >= 25
            assert page.total_pages >= 3
        finally:
            for qid in created_qids:
                try:
                    c.delete_post(qid)
                except NotFoundError:
                    pass


# E-P8 ------------------------------------------------------------------------
def test_create_post_auto_fetches_key(base_url):
    with Markpost(base_url, "markpost", "markpost") as c:
        # No post_key pre-seeded; create_post must fetch one automatically.
        created = c.create_post("auto-key post", BODY)
        assert created.id.startswith("p-")
        c.delete_post(created.id)


# E-P9 ------------------------------------------------------------------------
def test_create_post_invalid_post_key(admin_client):
    with pytest.raises(PermissionDeniedError) as exc_info:
        admin_client.create_post("x", "y", post_key="mpk-invalid-aaaaaaaaaaaaaaaa")
    assert exc_info.value.code == "invalid_post_key"


# E-P10 -----------------------------------------------------------------------
def test_create_post_empty_title_unprocessable(admin_client):
    with pytest.raises(UnprocessableEntityError):
        admin_client.create_post("", BODY)
