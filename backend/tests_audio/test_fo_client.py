"""Offline tests for the Wajo Fo alert. Never contacts Fo: FO_ALERTS is off or tokens are absent."""
import asyncio

from backend import fo_client


def test_request_names_all_three_actions_and_the_evidence(monkeypatch):
    monkeypatch.setenv("FAMILY_ALERT_PHONE", "+910000000000")
    monkeypatch.setenv("FAMILY_ALERT_EMAIL", "family@example.com")
    msg = fo_client.build_request(["pretending to be police"], ["आपके नाम पर arrest warrant जारी हो चुका है।"],
                                  32700, "hi-IN")
    assert "text message to +910000000000" in msg
    assert "email to family@example.com" in msg
    assert "Phone +910000000000" in msg
    assert "arrest warrant" in msg and "33 seconds into the call" in msg
    assert "1930" in msg or "nineteen thirty" in msg


def test_email_only_contact_skips_text_and_call(monkeypatch):
    monkeypatch.setenv("FAMILY_ALERT_PHONE", "")
    monkeypatch.setenv("FAMILY_ALERT_EMAIL", "family@example.com")
    msg = fo_client.build_request([], [], None, "ta-IN")
    assert "email to family@example.com" in msg
    assert "text message" not in msg and "Phone " not in msg


def test_switched_off_means_not_configured_and_no_network(monkeypatch):
    monkeypatch.setenv("FO_ALERTS", "off")
    monkeypatch.setenv("FAMILY_ALERT_PHONE", "+910000000000")
    assert fo_client.configured() is False
    res = asyncio.run(fo_client.alert_family(["x"], [], 1000))
    assert res == {"ok": False, "status": "not configured"}


def test_request_field_comes_from_the_schema():
    tool = {"inputSchema": {"properties": {"message": {"type": "string"}, "conversationId": {"type": "string"},
                                           "newConversation": {"type": "boolean"}}, "required": ["message"]}}
    assert fo_client._request_field(tool) == "message"
