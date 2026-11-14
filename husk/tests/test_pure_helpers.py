"""Pure-logic tests: no database, no network."""
import base64
import json
from datetime import datetime, timezone
from email import message_from_bytes

import pytest

from assistant.core.cron import CronError, cron_matches, validate_cron
from assistant.core.jsonschema_lite import validate_arguments
from assistant.core.redact import redact
from assistant.core.textutil import is_valid_email, like_pattern, make_snippet
from assistant.services.agent_runtime.planner import build_planner_prompt, validate_plan
from assistant.services.mail import common as mail
from assistant.services.mail import providers as providers

ALLOWED = {
    "notes.list": {"kind": "builtin", "description": "d", "requires_approval": False,
                   "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": [], "additionalProperties": False}},
    "notes.create": {"kind": "builtin", "description": "d", "requires_approval": True,
                     "input_schema": {"type": "object", "properties": {"title": {"type": "string", "maxLength": 240}}, "required": ["title"], "additionalProperties": False}},
    "mcp:s1:search": {"kind": "mcp", "description": "d", "requires_approval": True,
                      "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}},
}


def test_cron_matching():
    assert cron_matches("*/15 * * * *", datetime(2026, 10, 25, 10, 30))
    assert not cron_matches("*/15 * * * *", datetime(2026, 10, 25, 10, 31))
    assert cron_matches("0 9 * * 0", datetime(2026, 10, 25, 9, 0))  # 25 Oct 2026 is a Sunday
    assert not cron_matches("0 9 * * 1-5", datetime(2026, 10, 25, 9, 0))
    assert cron_matches("0 9 1,25 * 1", datetime(2026, 10, 25, 9, 0))  # day-of-month OR day-of-week


@pytest.mark.parametrize("bad", ["* * * *", "61 * * * *", "*/0 * * * *", "a * * * *", "5-1 * * * *"])
def test_cron_rejects_bad_expressions(bad):
    with pytest.raises(CronError):
        validate_cron(bad)


def test_text_helpers():
    assert like_pattern("50%_a") == "%50\\%\\_a%"
    assert "needle" in make_snippet("x " * 200 + "needle" + " y" * 200, "needle")
    assert is_valid_email("a@b.co") and not is_valid_email("a@b") and not is_valid_email("a b@c.de")


def test_redaction():
    assert "sk-abcdefghijk" not in redact("failed sk-abcdefghijklmnop")
    assert "SECRET123456" not in redact("x SECRET123456 y", ["SECRET123456"])
    assert "tok123456" not in redact("GET /x?access_token=tok123456&a=1")
    assert "abcdef1234" not in redact("Authorization: Bearer abcdef1234567890")


def test_argument_validation():
    schema = {"type": "object", "properties": {"title": {"type": "string", "maxLength": 5}, "n": {"type": "integer", "minimum": 1, "maximum": 3}}, "required": ["title"]}
    validate_arguments(schema, {"title": "ok", "n": 2})
    for bad in ({}, {"title": "toolong"}, {"title": "ok", "n": True}, {"title": "ok", "n": 9}, {"title": "ok", "zzz": 1}):
        with pytest.raises(ValueError):
            validate_arguments(schema, bad)
    validate_arguments(schema, {"title": "ok", "zzz": 1}, strict=False)


def test_plan_validation():
    plan = validate_plan(json.dumps({"steps": [{"tool": "notes.list", "arguments": {"limit": 5}}]}), ALLOWED)
    assert plan["steps"][0]["tool"] == "notes.list"
    assert validate_plan("Sure!\n```json\n{\"steps\":[],\"explanation\":\"nope\"}\n```", ALLOWED)["explanation"] == "nope"
    assert validate_plan({"steps": [{"tool": "mcp:s1:search", "arguments": {"q": "a", "extra": 1}}]}, ALLOWED)
    bad_plans = [
        {"steps": [{"tool": "shell.exec", "arguments": {}}]},
        {"steps": [{"tool": "notes.list", "arguments": {"all": True}}]},
        {"steps": [{"tool": "notes.create", "arguments": {}}]},
        {"steps": [{"tool": "notes.list", "arguments": {}}] * 6},
        {"steps": [], "x": 1},
        {"steps": [{"tool": "notes.list"}]},
    ]
    for bad in bad_plans:
        with pytest.raises(ValueError):
            validate_plan(bad, ALLOWED)
    assert "notes.list" in build_planner_prompt("hello", ALLOWED, "be brief")


def test_pkce_matches_rfc7636_vector():
    assert mail.code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert 43 <= len(mail.new_code_verifier()) <= 128


def test_mail_parsing_and_mime():
    assert mail.parse_address("Ann Lee <Ann@Example.com>") == {"name": "Ann Lee", "email": "ann@example.com"}
    assert mail.parse_iso("2026-10-25T10:00:00.0000000") == datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    start = mail.parse_date_start("2026-10-25")
    assert mail.all_day_end(mail.parse_date_start("2026-10-26"), start) == datetime(2026, 10, 25, 23, 59, 59, tzinfo=timezone.utc)
    mime = mail.build_mime("me@x.io", mail.OutgoingMessage(to=["a@y.io"], subject="Hi", body="<p>Hello</p>", html=True),
                           in_reply_to="<id1@x>", references="<id0@x>")
    parsed = message_from_bytes(mime.as_bytes())
    assert parsed["In-Reply-To"] == "<id1@x>" and parsed["References"] == "<id0@x> <id1@x>" and parsed.is_multipart()
    to, cc = mail.addresses_for_reply({"email": "o@z.io"}, "", [{"email": "me@x.io"}, {"email": "p@z.io"}], [], "me@x.io", True)
    assert to == ["o@z.io"] and cc == ["p@z.io"]


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_gmail_and_graph_parsers():
    item = {"id": "m1", "threadId": "t1", "labelIds": ["INBOX", "UNREAD"], "snippet": "hey", "internalDate": "1790000000000",
            "payload": {"mimeType": "multipart/mixed", "headers": [{"name": "From", "value": "Bob <bob@x.io>"}, {"name": "Subject", "value": "Yo"}],
                        "parts": [{"mimeType": "multipart/alternative", "parts": [{"mimeType": "text/plain", "body": {"data": _b64("plain")}},
                                                                                  {"mimeType": "text/html", "body": {"data": _b64("<b>h</b>")}}]},
                                  {"mimeType": "application/pdf", "filename": "a.pdf", "body": {}}]}}
    msg = providers.parse_gmail_message(item, "inbox")
    assert (msg.sender_email, msg.is_read, msg.has_attachments, msg.body_text, msg.body_html) == ("bob@x.io", False, True, "plain", "<b>h</b>")
    event = providers.parse_google_event({"id": "e", "start": {"date": "2026-10-25"}, "end": {"date": "2026-10-26"}})
    assert event.all_day and event.end_at.day == 25
    assert providers.parse_google_event({"id": "c", "status": "cancelled", "start": {"date": "2026-10-25"}}) is None
    graph = providers.parse_graph_message({"id": "A=", "subject": "S", "from": {"emailAddress": {"name": "Z", "address": "Z@X.io"}},
                                           "receivedDateTime": "2026-10-25T08:00:00Z", "isRead": False,
                                           "body": {"contentType": "html", "content": "<p>x</p>"}}, "inbox")
    assert graph.sender_email == "z@x.io" and graph.body_html == "<p>x</p>" and not graph.is_read
    assert providers.parse_graph_event({"id": "g", "isCancelled": True, "start": {"dateTime": "2026-10-25T10:00:00"}}) is None
