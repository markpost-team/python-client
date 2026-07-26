"""E2E: admin endpoints (TESTING §5.4.5)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


# E-AD1 -----------------------------------------------------------------------
def test_admin_list_users_includes_seed(admin_client):
    page = admin_client.admin_list_users()
    usernames = {u.username for u in page.items}
    assert "markpost" in usernames
    seed = next(u for u in page.items if u.username == "markpost")
    assert seed.role == "admin"


# E-AD2 / E-AD3 ---------------------------------------------------------------
def test_admin_list_posts_and_delete(admin_client):
    created = admin_client.create_post("admin-list-post", "# body")
    qid = created.id
    try:
        page = admin_client.admin_list_posts(limit=100)
        qids = {p.qid for p in page.items}
        assert qid in qids
    finally:
        admin_client.admin_delete_post(qid)
    # After deletion it's gone.
    page = admin_client.admin_list_posts(limit=100)
    assert qid not in {p.qid for p in page.items}


# E-AD3 search ----------------------------------------------------------------
def test_admin_list_posts_search(admin_client):
    admin_client.create_post("unique-searchable-title-xyz", "# body")
    # search is a substring match server-side; give the suite some leeway.
    page = admin_client.admin_list_posts(search="unique-searchable-title-xyz")
    assert any("unique-searchable-title-xyz" in p.title for p in page.items)


# E-AD5 -----------------------------------------------------------------------
def test_admin_list_channels_and_history(admin_client):
    channels = admin_client.admin_list_channels()
    assert hasattr(channels, "items")
    history = admin_client.admin_list_delivery_history()
    assert hasattr(history, "items")
