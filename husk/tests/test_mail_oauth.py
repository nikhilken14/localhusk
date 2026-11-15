"""Mail/OAuth flow against a fake provider (no network)."""
from datetime import datetime, timezone

from assistant.db.models import CalendarEvent, MailAccount, MailMessage, OAuthState
from assistant.services.mail import providers as provider_module
from assistant.services.mail.common import RemoteCalendar, RemoteEvent, RemoteMessage, TokenSet
from conftest import API


class FakeGoogle:
    name = "google"
    sent = []

    def configured(self): return True
    def setup_hint(self): return ""
    def scopes(self, cal): return ["x"]
    def authorization_url(self, redirect_uri, state, challenge, include_calendar): return f"https://accounts.example/auth?state={state}"
    def exchange_code(self, code, verifier, redirect_uri):
        assert code == "good-code" and verifier
        return TokenSet("access-1", "refresh-1", 3600, "https://www.googleapis.com/auth/calendar.readonly")
    def refresh(self, token): return TokenSet("access-2", None, 3600)
    def profile(self, token): return "me@example.com", "Me"
    def revoke(self, token): return True
    def list_messages(self, token, folder, limit):
        return [RemoteMessage("m1", folder, subject="Hello", sender_email="a@b.io", snippet="hi", is_read=False,
                              received_at=datetime(2026, 10, 25, tzinfo=timezone.utc))] if folder == "inbox" else []
    def get_message(self, token, external_id, folder):
        return RemoteMessage(external_id, folder, body_text="Full body", body_loaded=True)
    def set_read(self, token, external_id, is_read): self.read = is_read
    def send(self, token, sender, message): self.sent.append(("new", sender, message.to))
    def reply(self, token, sender, external_id, body, html, reply_all): self.sent.append(("reply", external_id, reply_all))
    def list_calendars(self, token): return [RemoteCalendar("primary", "Main")]
    def list_events(self, token, cid, start, end):
        return [RemoteEvent("e1", "Standup", datetime.now(timezone.utc), None)]


def _connect(client, monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(provider_module, "_PROVIDERS", {"google": fake})
    start = client.post(f"{API}/mail/accounts/oauth/start", json={"provider": "google"})
    assert start.status_code == 200, start.text
    state = start.json()["state"]
    page = client.get(f"{API}/mail/accounts/oauth/callback?code=good-code&state={state}")
    assert page.status_code == 200 and "connected" in page.text
    return fake, state


def test_oauth_flow_state_is_single_use_and_secret_not_exposed(client, monkeypatch, db):
    fake, state = _connect(client, monkeypatch)
    account = client.get(f"{API}/mail/accounts").json()[0]
    assert account["email"] == "me@example.com" and account["has_calendar"] is True and "credential_ref" not in account
    assert db.get(OAuthState, state) is None
    replay = client.get(f"{API}/mail/accounts/oauth/callback?code=good-code&state={state}")
    assert replay.status_code == 400
    assert client.get(f"{API}/mail/accounts/oauth/callback?error=access_denied").status_code == 400


def test_unconfigured_provider_gives_actionable_error(client):
    r = client.post(f"{API}/mail/accounts/oauth/start", json={"provider": "microsoft"})
    assert r.status_code == 400 and r.json()["code"] == "oauth_not_configured" and "MICROSOFT_CLIENT_ID" in r.json()["detail"]


def test_sync_read_send_reply_and_disconnect(client, monkeypatch, db):
    fake, _ = _connect(client, monkeypatch)
    account_id = client.get(f"{API}/mail/accounts").json()[0]["id"]
    assert client.post(f"{API}/mail/sync").json()["synced"][0]["messages_added"] == 1
    assert client.post(f"{API}/mail/sync", json={"account_id": account_id}).json()["synced"][0]["messages_added"] == 0
    listing = client.get(f"{API}/mail/messages?unread=true").json()
    assert listing["total"] == 1 and listing["items"][0]["sender"]["email"] == "a@b.io"
    assert client.get(f"{API}/mail/messages?q=nomatch").json()["total"] == 0
    mid = listing["items"][0]["id"]
    assert client.get(f"{API}/mail/messages/{mid}").json()["body_text"] == "Full body"  # lazily fetched
    assert client.patch(f"{API}/mail/messages/{mid}", json={"is_read": True}).json()["is_read"] is True and fake.read is True
    assert client.post(f"{API}/mail/send", json={"account_id": account_id, "to": ["x@y.io"], "body": "yo"}).status_code == 202
    assert client.post(f"{API}/mail/send", json={"account_id": account_id, "to": ["not-an-email"], "body": "yo"}).status_code == 422
    assert client.post(f"{API}/mail/messages/{mid}/send-reply", json={"body": "ok", "reply_all": True}).status_code == 202
    assert fake.sent == [("new", "me@example.com", ["x@y.io"]), ("reply", "m1", True)]
    assert client.post(f"{API}/calendar/sync").json()["synced"] == []  # calendar is local-only; no provider sync
    gone = client.delete(f"{API}/mail/accounts/{account_id}").json()
    assert gone == {"deleted": True, "revoked": True}
    assert db.query(MailAccount).count() == 0 and db.query(MailMessage).count() == 0
    assert db.query(CalendarEvent).filter_by(source="google").count() == 0  # cascades with the account
