"""Gmail/Google Calendar and Microsoft Graph clients (plain httpx, synchronous).

These talk to live provider APIs.  They are written against the public REST docs and unit-tested
for their pure parsing functions, but must be exercised against real accounts before relying on them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote, urlencode

import httpx

from assistant.core.config import get_settings
from assistant.services.mail.common import (
    OutgoingMessage, ProviderError, ReauthRequired, RemoteCalendar, RemoteEvent, RemoteMessage, TokenSet,
    addresses_for_reply, all_day_end, b64url, b64url_decode, build_mime, parse_address, parse_address_list,
    parse_date_start, parse_iso, reply_subject,
)

CALENDAR_SCOPE_GOOGLE = "https://www.googleapis.com/auth/calendar.readonly"
CALENDAR_SCOPE_MICROSOFT = "Calendars.Read"


def _http_error(response: httpx.Response) -> ProviderError:
    text = response.text[:300].replace("\n", " ")
    if response.status_code == 401:
        return ReauthRequired("The provider rejected the access token", 401)
    return ProviderError(f"Provider returned HTTP {response.status_code}: {text}", response.status_code)


class _BaseProvider:
    name = ""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))

    # -- low level
    def _send(self, method: str, url: str, token: str | None = None, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach the provider: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise _http_error(response)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("The provider returned a non-JSON response") from exc

    def _token_request(self, url: str, data: dict) -> TokenSet:
        try:
            response = self._client.post(url, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not reach the provider: {type(exc).__name__}") from exc
        body = {}
        try:
            body = response.json()
        except ValueError:
            pass
        if response.status_code >= 400:
            if body.get("error") in {"invalid_grant", "interaction_required", "consent_required"}:
                raise ReauthRequired("The authorization is no longer valid; reconnect the account", response.status_code)
            description = str(body.get("error_description") or body.get("error") or response.status_code)[:200]
            raise ProviderError(f"Token request failed: {description}", response.status_code)
        return TokenSet(body["access_token"], body.get("refresh_token"), int(body.get("expires_in", 3600)), body.get("scope", ""))


# ====================================================================== Google
GMAIL_LABELS = {"inbox": "INBOX", "sent": "SENT", "drafts": "DRAFT", "trash": "TRASH", "spam": "SPAM"}


def gmail_extract_bodies(payload: dict) -> tuple[str, str, bool]:
    """Walk a Gmail MIME payload -> (text, html, has_attachments)."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments = False

    def walk(part: dict) -> None:
        nonlocal attachments
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if part.get("filename"):
            attachments = True
        elif mime == "text/plain" and data:
            text_parts.append(b64url_decode(data))
        elif mime == "text/html" and data:
            html_parts.append(b64url_decode(data))
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return "\n".join(text_parts), "\n".join(html_parts), attachments


def parse_gmail_message(item: dict, folder: str) -> RemoteMessage:
    headers = {h["name"].lower(): h["value"] for h in (item.get("payload") or {}).get("headers", [])}
    sender = parse_address(headers.get("from", ""))
    text, html, has_attachments = gmail_extract_bodies(item.get("payload") or {})
    received = datetime.fromtimestamp(int(item["internalDate"]) / 1000, timezone.utc) if item.get("internalDate") else None
    return RemoteMessage(
        external_id=item["id"], thread_id=item.get("threadId", ""), folder=folder,
        subject=headers.get("subject", ""), sender_name=sender["name"], sender_email=sender["email"],
        to=parse_address_list(headers.get("to", "")), cc=parse_address_list(headers.get("cc", "")),
        snippet=item.get("snippet", ""), body_text=text, body_html=html, body_loaded=bool(text or html),
        is_read="UNREAD" not in item.get("labelIds", []), has_attachments=has_attachments,
        received_at=received, rfc_message_id=headers.get("message-id", ""),
    )


def parse_google_event(item: dict) -> RemoteEvent | None:
    if item.get("status") == "cancelled" or "start" not in item:
        return None
    start, end = item["start"], item.get("end") or {}
    if "date" in start:
        start_at = parse_date_start(start["date"])
        if start_at is None:
            return None
        end_at = all_day_end(parse_date_start(end.get("date", "")), start_at)
        all_day = True
    else:
        start_at = parse_iso(start.get("dateTime"))
        if start_at is None:
            return None
        end_at, all_day = parse_iso(end.get("dateTime")), False
    return RemoteEvent(item["id"], item.get("summary") or "(no title)", start_at, end_at,
                       (item.get("description") or "")[:5000], item.get("location") or "", all_day)


class GoogleProvider(_BaseProvider):
    name = "google"
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    API = "https://gmail.googleapis.com/gmail/v1/users/me"
    CAL = "https://www.googleapis.com/calendar/v3"
    BASE_SCOPES = ["openid", "email", "profile", "https://www.googleapis.com/auth/gmail.modify",
                   "https://www.googleapis.com/auth/gmail.send"]

    def configured(self) -> bool:
        return bool(get_settings().google_client_id and get_settings().google_client_secret)

    def setup_hint(self) -> str:
        return "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (Google Cloud OAuth client of type 'Web application')."

    def scopes(self, include_calendar: bool) -> list[str]:
        return self.BASE_SCOPES + ([CALENDAR_SCOPE_GOOGLE] if include_calendar else [])

    def authorization_url(self, redirect_uri: str, state: str, challenge: str, include_calendar: bool) -> str:
        params = {
            "client_id": get_settings().google_client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": " ".join(self.scopes(include_calendar)), "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent",
            "include_granted_scopes": "true",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> TokenSet:
        s = get_settings()
        return self._token_request(self.TOKEN_URL, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier,
            "client_id": s.google_client_id, "client_secret": s.google_client_secret})

    def refresh(self, refresh_token: str) -> TokenSet:
        s = get_settings()
        return self._token_request(self.TOKEN_URL, {
            "grant_type": "refresh_token", "refresh_token": refresh_token,
            "client_id": s.google_client_id, "client_secret": s.google_client_secret})

    def profile(self, token: str) -> tuple[str, str]:
        data = self._send("GET", "https://openidconnect.googleapis.com/v1/userinfo", token)
        if not data.get("email"):
            raise ProviderError("The provider did not return an email address")
        return data["email"].lower(), data.get("name", "")

    def revoke(self, token: str) -> bool:
        try:
            self._client.post("https://oauth2.googleapis.com/revoke", data={"token": token})
            return True
        except httpx.HTTPError:
            return False

    def list_messages(self, token: str, folder: str, limit: int) -> list[RemoteMessage]:
        label = GMAIL_LABELS[folder]
        listing = self._send("GET", f"{self.API}/messages", token, params={
            "labelIds": label, "maxResults": limit, "includeSpamTrash": str(folder in ("trash", "spam")).lower()})
        messages = []
        for ref in listing.get("messages", []):
            item = self._send("GET", f"{self.API}/messages/{ref['id']}", token, params={
                "format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Message-Id"]})
            messages.append(parse_gmail_message(item, folder))
        return messages

    def get_message(self, token: str, external_id: str, folder: str) -> RemoteMessage:
        item = self._send("GET", f"{self.API}/messages/{external_id}", token, params={"format": "full"})
        return parse_gmail_message(item, folder)

    def set_read(self, token: str, external_id: str, is_read: bool) -> None:
        body = {"removeLabelIds": ["UNREAD"]} if is_read else {"addLabelIds": ["UNREAD"]}
        self._send("POST", f"{self.API}/messages/{external_id}/modify", token, json=body)

    def send(self, token: str, sender: str, message: OutgoingMessage) -> None:
        raw = b64url(build_mime(sender, message).as_bytes())
        self._send("POST", f"{self.API}/messages/send", token, json={"raw": raw})

    def reply(self, token: str, sender: str, external_id: str, body: str, html: bool, reply_all: bool) -> None:
        item = self._send("GET", f"{self.API}/messages/{external_id}", token, params={
            "format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Message-Id", "References", "Reply-To"]})
        headers = {h["name"].lower(): h["value"] for h in item.get("payload", {}).get("headers", [])}
        to, cc = addresses_for_reply(parse_address(headers.get("from", "")), headers.get("reply-to", ""),
                                     parse_address_list(headers.get("to", "")), parse_address_list(headers.get("cc", "")),
                                     sender, reply_all)
        if not to:
            raise ProviderError("The original message has no sender to reply to")
        outgoing = OutgoingMessage(to=to, cc=cc, subject=reply_subject(headers.get("subject", "")), body=body, html=html)
        raw = b64url(build_mime(sender, outgoing, in_reply_to=headers.get("message-id", ""),
                                references=headers.get("references", "")).as_bytes())
        self._send("POST", f"{self.API}/messages/send", token, json={"raw": raw, "threadId": item.get("threadId")})

    def list_calendars(self, token: str) -> list[RemoteCalendar]:
        data = self._send("GET", f"{self.CAL}/users/me/calendarList", token, params={"minAccessRole": "reader"})
        return [RemoteCalendar(c["id"], c.get("summaryOverride") or c.get("summary") or c["id"],
                               c.get("backgroundColor") or "#4f8cff") for c in data.get("items", [])]

    def list_events(self, token: str, calendar_id: str, start: datetime, end: datetime) -> list[RemoteEvent]:
        events: list[RemoteEvent] = []
        params = {"timeMin": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "timeMax": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
        for _ in range(10):  # hard page cap
            data = self._send("GET", f"{self.CAL}/calendars/{quote(calendar_id, safe='')}/events", token, params=params)
            events.extend(e for e in (parse_google_event(i) for i in data.get("items", [])) if e)
            if not data.get("nextPageToken"):
                break
            params = {**params, "pageToken": data["nextPageToken"]}
        return events


# ==================================================================== Microsoft
GRAPH = "https://graph.microsoft.com/v1.0"
GRAPH_FOLDERS = {"inbox": "inbox", "sent": "sentitems", "drafts": "drafts", "trash": "deleteditems", "spam": "junkemail"}
GRAPH_SELECT = ("id,conversationId,subject,from,toRecipients,ccRecipients,bodyPreview,receivedDateTime,"
                "isRead,hasAttachments,internetMessageId")


def _graph_addresses(items: list[dict] | None) -> list[dict]:
    out = []
    for item in items or []:
        info = item.get("emailAddress") or {}
        if info.get("address"):
            out.append({"name": info.get("name", ""), "email": info["address"].lower()})
    return out


def parse_graph_message(item: dict, folder: str) -> RemoteMessage:
    sender = ((item.get("from") or {}).get("emailAddress")) or {}
    body = item.get("body") or {}
    content = body.get("content", "")
    is_html = str(body.get("contentType", "")).lower() == "html"
    return RemoteMessage(
        external_id=item["id"], thread_id=item.get("conversationId", ""), folder=folder,
        subject=item.get("subject") or "", sender_name=sender.get("name", ""), sender_email=(sender.get("address") or "").lower(),
        to=_graph_addresses(item.get("toRecipients")), cc=_graph_addresses(item.get("ccRecipients")),
        snippet=item.get("bodyPreview", ""), body_text="" if is_html else content, body_html=content if is_html else "",
        body_loaded=bool(content), is_read=bool(item.get("isRead")), has_attachments=bool(item.get("hasAttachments")),
        received_at=parse_iso(item.get("receivedDateTime")), rfc_message_id=item.get("internetMessageId", ""),
    )


def parse_graph_event(item: dict) -> RemoteEvent | None:
    if item.get("isCancelled"):
        return None
    start_at = parse_iso((item.get("start") or {}).get("dateTime"))
    if start_at is None:
        return None
    end_raw = parse_iso((item.get("end") or {}).get("dateTime"))
    all_day = bool(item.get("isAllDay"))
    end_at = all_day_end(end_raw, start_at) if all_day else end_raw
    return RemoteEvent(item["id"], item.get("subject") or "(no title)", start_at, end_at,
                       (item.get("bodyPreview") or "")[:5000], ((item.get("location") or {}).get("displayName")) or "", all_day)


class MicrosoftProvider(_BaseProvider):
    name = "microsoft"
    BASE_SCOPES = ["offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send"]

    def configured(self) -> bool:
        return bool(get_settings().microsoft_client_id)

    def setup_hint(self) -> str:
        return ("Set MICROSOFT_CLIENT_ID (Entra app registration with a 'Web' redirect URI; "
                "MICROSOFT_CLIENT_SECRET is optional when using PKCE) and optionally MICROSOFT_TENANT.")

    def _endpoint(self, kind: str) -> str:
        return f"https://login.microsoftonline.com/{get_settings().microsoft_tenant}/oauth2/v2.0/{kind}"

    def scopes(self, include_calendar: bool) -> list[str]:
        return self.BASE_SCOPES + ([CALENDAR_SCOPE_MICROSOFT] if include_calendar else [])

    def authorization_url(self, redirect_uri: str, state: str, challenge: str, include_calendar: bool) -> str:
        params = {
            "client_id": get_settings().microsoft_client_id, "response_type": "code", "redirect_uri": redirect_uri,
            "response_mode": "query", "scope": " ".join(self.scopes(include_calendar)), "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
        }
        return f"{self._endpoint('authorize')}?{urlencode(params)}"

    def _token_data(self, data: dict, scopes: str) -> dict:
        s = get_settings()
        data = {**data, "client_id": s.microsoft_client_id, "scope": scopes}
        if s.microsoft_client_secret:
            data["client_secret"] = s.microsoft_client_secret
        return data

    def exchange_code(self, code: str, verifier: str, redirect_uri: str) -> TokenSet:
        return self._token_request(self._endpoint("token"), self._token_data({
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier},
            " ".join(self.BASE_SCOPES + [CALENDAR_SCOPE_MICROSOFT])))

    def refresh(self, refresh_token: str) -> TokenSet:
        return self._token_request(self._endpoint("token"), self._token_data(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}, " ".join(self.BASE_SCOPES + [CALENDAR_SCOPE_MICROSOFT])))

    def profile(self, token: str) -> tuple[str, str]:
        data = self._send("GET", f"{GRAPH}/me", token, params={"$select": "mail,userPrincipalName,displayName"})
        email = (data.get("mail") or data.get("userPrincipalName") or "").lower()
        if not email:
            raise ProviderError("The provider did not return an email address")
        return email, data.get("displayName", "")

    def revoke(self, token: str) -> bool:
        return False  # Microsoft identity platform has no per-token revocation endpoint

    def list_messages(self, token: str, folder: str, limit: int) -> list[RemoteMessage]:
        data = self._send("GET", f"{GRAPH}/me/mailFolders/{GRAPH_FOLDERS[folder]}/messages", token, params={
            "$top": limit, "$orderby": "receivedDateTime desc", "$select": GRAPH_SELECT})
        return [parse_graph_message(i, folder) for i in data.get("value", [])]

    def get_message(self, token: str, external_id: str, folder: str) -> RemoteMessage:
        item = self._send("GET", f"{GRAPH}/me/messages/{external_id}", token, params={"$select": GRAPH_SELECT + ",body"})
        return parse_graph_message(item, folder)

    def set_read(self, token: str, external_id: str, is_read: bool) -> None:
        self._send("PATCH", f"{GRAPH}/me/messages/{external_id}", token, json={"isRead": is_read})

    @staticmethod
    def _recipients(addresses: list[str]) -> list[dict]:
        return [{"emailAddress": {"address": a}} for a in addresses]

    def send(self, token: str, sender: str, message: OutgoingMessage) -> None:
        payload = {"message": {
            "subject": message.subject,
            "body": {"contentType": "HTML" if message.html else "Text", "content": message.body},
            "toRecipients": self._recipients(message.to), "ccRecipients": self._recipients(message.cc),
            "bccRecipients": self._recipients(message.bcc)}, "saveToSentItems": True}
        self._send("POST", f"{GRAPH}/me/sendMail", token, json=payload)

    def reply(self, token: str, sender: str, external_id: str, body: str, html: bool, reply_all: bool) -> None:
        action = "replyAll" if reply_all else "reply"
        payload = ({"message": {"body": {"contentType": "HTML", "content": body}}, "comment": ""} if html else {"comment": body})
        self._send("POST", f"{GRAPH}/me/messages/{external_id}/{action}", token, json=payload)

    def list_calendars(self, token: str) -> list[RemoteCalendar]:
        data = self._send("GET", f"{GRAPH}/me/calendars", token)
        return [RemoteCalendar(c["id"], c.get("name") or "Calendar", c.get("hexColor") or "#4f8cff") for c in data.get("value", [])]

    def list_events(self, token: str, calendar_id: str, start: datetime, end: datetime) -> list[RemoteEvent]:
        events: list[RemoteEvent] = []
        url: str | None = f"{GRAPH}/me/calendars/{quote(calendar_id, safe='')}/calendarView"
        params: dict | None = {"startDateTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "$top": 100, "$select": "id,subject,bodyPreview,start,end,location,isAllDay,isCancelled"}
        for _ in range(10):
            data = self._send("GET", url, token, params=params, headers={"Prefer": 'outlook.timezone="UTC"'})
            events.extend(e for e in (parse_graph_event(i) for i in data.get("value", [])) if e)
            url, params = data.get("@odata.nextLink"), None  # nextLink already carries the query
            if not url:
                break
        return events


_PROVIDERS: dict[str, _BaseProvider] = {}


def get_provider(name: str) -> _BaseProvider | None:
    if name not in ("google", "microsoft"):
        return None
    if name not in _PROVIDERS:
        _PROVIDERS[name] = GoogleProvider() if name == "google" else MicrosoftProvider()
    return _PROVIDERS[name]
