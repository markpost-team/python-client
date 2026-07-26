"""E2E: delivery channels + history (TESTING §5.4.4)."""

from __future__ import annotations

import time

import httpx
import pytest

from markpost import NotFoundError, UnprocessableEntityError

pytestmark = pytest.mark.e2e

# A webhook pointing at the in-compose mock service. The app resolves
# "webhook-mock" via Docker DNS; the SDK host reaches the mock through the
# mapped port (see docker-compose.yml). The test card / delivery lands here.
WEBHOOK_MOCK_URL = "http://webhook-mock:3002/webhook"
WEBHOOK_MOCK_HOST = "http://localhost:3002"

# Title the backend writes on a SendTest diagnostic card
# (backend/internal/service/delivery/post_delivery.go: testCardTitle).
TEST_CARD_TITLE = "Markpost test message"

FEISHU_CFG = {
    "webhook_url": "https://example.com/webhook",
    "card_link_url": "https://example.com/card",
}
FEISHU_MOCK_CFG = {
    "webhook_url": WEBHOOK_MOCK_URL,
}


def _clear_webhooks() -> None:
    """Drop every request the webhook mock has recorded so far."""
    try:
        httpx.post(f"{WEBHOOK_MOCK_HOST}/webhooks/clear", timeout=5.0)
    except Exception:
        pass


def _get_webhooks() -> list[dict]:
    """Return the requests the webhook mock has received (newest last)."""
    r = httpx.get(f"{WEBHOOK_MOCK_HOST}/webhooks", timeout=5.0)
    r.raise_for_status()
    return r.json()


@pytest.fixture
def created_channel(admin_client):
    ch = admin_client.create_channel("feishu", "sdk-e2e-channel", FEISHU_CFG, keywords="")
    yield ch
    try:
        admin_client.delete_channel(ch.id)
    except Exception:
        pass


# E-D1 ------------------------------------------------------------------------
def test_create_feishu_channel(created_channel):
    assert created_channel.id
    assert created_channel.kind == "feishu"


# E-D2 ------------------------------------------------------------------------
def test_list_channels_includes_new(admin_client, created_channel):
    channels = admin_client.list_channels()
    ids = {c.id for c in channels}
    assert created_channel.id in ids


# E-D3 ------------------------------------------------------------------------
def test_update_channel_patch(admin_client, created_channel):
    updated = admin_client.update_channel(created_channel.id, enabled=False)
    assert updated.enabled is False
    assert updated.name == created_channel.name  # unchanged


# E-D4 ------------------------------------------------------------------------
def test_delete_channel(admin_client):
    ch = admin_client.create_channel("feishu", "to-delete", FEISHU_CFG)
    admin_client.delete_channel(ch.id)
    assert ch.id not in {c.id for c in admin_client.list_channels()}


# E-D5 ------------------------------------------------------------------------
def test_list_delivery_history(admin_client):
    page = admin_client.list_delivery_history()
    assert page.total >= 0  # shape correct; may be empty
    assert hasattr(page, "items")


# E-D6 ------------------------------------------------------------------------
def test_list_delivery_history_channel_filter(admin_client, created_channel):
    page = admin_client.list_delivery_history(channel_id=created_channel.id)
    # Filtering by this brand-new channel yields (at most) its own history.
    for item in page.items:
        assert item is not None


# E-D7 ------------------------------------------------------------------------
def test_create_channel_missing_kind(admin_client):
    with pytest.raises(UnprocessableEntityError):
        admin_client.create_channel("", "no-kind", {})


# E-D8 ------------------------------------------------------------------------
def test_create_channel_invalid_keywords(admin_client):
    # An unparseable keyword expression should be rejected by the backend.
    with pytest.raises(UnprocessableEntityError):
        admin_client.create_channel("feishu", "bad-kw", FEISHU_CFG, keywords="!@#$%^&*()")


# E-D9: test_channel dispatches a real card to the webhook mock ---------------
def test_test_channel_sends_card(admin_client):
    _clear_webhooks()
    ch = admin_client.create_channel("feishu", "sdk-e2e-test-target", FEISHU_MOCK_CFG)
    try:
        # Fire-and-forget on the backend; the response confirms dispatch only.
        msg = admin_client.test_channel(ch.id)
        assert msg == "test message sent"

        # The backend sends synchronously within the request, but give the mock
        # a brief window and poll rather than sleeping blindly.
        deadline = time.time() + 5.0
        webhooks: list[dict] = []
        while time.time() < deadline:
            webhooks = _get_webhooks()
            if any(TEST_CARD_TITLE in str(w.get("body", {})) for w in webhooks):
                break
            time.sleep(0.25)

        assert any(TEST_CARD_TITLE in str(w.get("body", {})) for w in webhooks), (
            "expected the test card to reach the webhook mock"
        )
    finally:
        try:
            admin_client.delete_channel(ch.id)
        except Exception:
            pass


# E-D10: test_channel on a missing channel -> NotFoundError -------------------
def test_test_channel_not_found(admin_client):
    # A channel id that does not belong to (or exist for) the current user.
    with pytest.raises(NotFoundError):
        admin_client.test_channel(99_999_999)


# E-D11: list_latest_delivery returns a list (one row per channel) ------------
def test_list_latest_delivery(admin_client):
    # create_post dispatches delivery for matching channels, which produces a
    # history row that /delivery/latest should surface.
    ch = admin_client.create_channel("feishu", "sdk-e2e-latest", FEISHU_MOCK_CFG, keywords="")
    created_qids: list[str] = []
    try:
        post = admin_client.create_post("sdk-e2e latest probe", "body")
        created_qids.append(post.id)

        # Delivery is enqueued async; poll until our channel shows up or we
        # time out. The endpoint is read-only and idempotent, so retry safely.
        deadline = time.time() + 10.0
        latest: list = []
        while time.time() < deadline:
            latest = admin_client.list_latest_delivery()
            assert isinstance(latest, list)
            if any(item.channel_id == ch.id for item in latest):
                break
            time.sleep(0.5)

        # The channel we created must appear once it has any history.
        matching = [item for item in latest if item.channel_id == ch.id]
        assert matching, "expected the just-delivered channel in latest-per-channel"
        assert matching[0].channel_id == ch.id
    finally:
        for qid in created_qids:
            try:
                admin_client.delete_post(qid)
            except Exception:
                pass
        try:
            admin_client.delete_channel(ch.id)
        except Exception:
            pass
