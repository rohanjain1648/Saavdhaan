"""Wajo Fo client: when Saavdhaan warns, ask Fo to text, email and call the family.

Fo is reached through its MCP server (https://mcp.api.wajo.ai/fo, streamable HTTP, OAuth). Sign in
once with `python -m backend.fo_login`; tokens live in .fo_tokens.json (gitignored) and are refreshed
here. Contact details come from .env:

    FAMILY_ALERT_PHONE=+91...
    FAMILY_ALERT_EMAIL=...

Fo works asynchronously: ask_fo returns quickly (often with status "working") and Fo carries out the
texts, email and call on its own schedule. `follow(conversation_id)` polls get_fo_reply for progress.
"""
from __future__ import annotations

import json
import logging
import re
import os
import time
from pathlib import Path

import httpx

from backend.risk.llm_judge import SSL_CONTEXT

log = logging.getLogger("saavdhaan.fo")

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / ".fo_tokens.json"
MCP_URL = os.environ.get("FO_MCP_URL", "https://mcp.api.wajo.ai/fo")
PROTOCOL = "2025-06-18"

# Last outcome, shown on /health.
LAST_STATUS: dict = {"state": "not used yet"}


class FoError(Exception):
    pass


def contacts() -> tuple[str, str]:
    return os.environ.get("FAMILY_ALERT_PHONE", "").strip(), os.environ.get("FAMILY_ALERT_EMAIL", "").strip()


def configured() -> bool:
    phone, email = contacts()
    return TOKENS.exists() and bool(phone or email) and os.environ.get("FO_ALERTS", "on").lower() != "off"


def _record(state: str, detail: str = "", **extra) -> None:
    LAST_STATUS.clear()
    LAST_STATUS.update({"state": state, "detail": detail, "at": time.strftime("%H:%M:%S"), **extra})


# ---- tokens --------------------------------------------------------------------------------------
def _load() -> dict:
    if not TOKENS.exists():
        raise FoError("not signed in to Fo: run  python -m backend.fo_login")
    return json.loads(TOKENS.read_text(encoding="utf-8"))


async def _refresh(client: httpx.AsyncClient, tok: dict) -> dict:
    if not tok.get("refresh_token"):
        raise FoError("Fo session expired and there is no refresh token: run  python -m backend.fo_login")
    r = await client.post(tok["token_endpoint"], data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        "client_id": tok["client_id"], "resource": MCP_URL,
    })
    if r.status_code != 200:
        raise FoError(f"Fo token refresh failed: HTTP {r.status_code} {r.text[:200]}")
    t = r.json()
    tok.update({
        "access_token": t["access_token"],
        "refresh_token": t.get("refresh_token", tok["refresh_token"]),
        "expires_at": time.time() + float(t.get("expires_in", 3600)) - 60,
    })
    TOKENS.write_text(json.dumps(tok, indent=2), encoding="utf-8")
    return tok


# ---- minimal MCP (streamable HTTP) session ---------------------------------------------------------
class FoSession:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.tok = _load()
        self.session_id: str | None = None
        self._id = 0

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.tok['access_token']}", "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    async def _post(self, payload: dict, retry: bool = True) -> httpx.Response:
        if time.time() >= self.tok.get("expires_at", 0):
            self.tok = await _refresh(self.client, self.tok)
        r = await self.client.post(MCP_URL, headers=self._headers(), json=payload)
        if r.status_code == 401 and retry:
            self.tok = await _refresh(self.client, self.tok)
            return await self._post(payload, retry=False)
        return r

    @staticmethod
    def _parse(r: httpx.Response, want_id: int) -> dict:
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        msg = json.loads(line[5:].strip())
                    except ValueError:
                        continue
                    if msg.get("id") == want_id:
                        return msg
            raise FoError(f"no reply to request {want_id} in Fo's event stream")
        return r.json()

    async def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        rid = self._id
        r = await self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        if r.status_code >= 400:
            raise FoError(f"Fo {method}: HTTP {r.status_code} {r.text[:300]}")
        if r.headers.get("mcp-session-id"):
            self.session_id = r.headers["mcp-session-id"]
        msg = self._parse(r, rid)
        if "error" in msg:
            raise FoError(f"Fo {method}: {msg['error']}")
        return msg.get("result", {})

    async def notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    async def open(self) -> dict:
        info = await self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                 "clientInfo": {"name": "saavdhaan", "version": "1.0"}})
        await self.notify("notifications/initialized")
        return info

    async def tools(self) -> list[dict]:
        return (await self.request("tools/list")).get("tools", [])

    async def call(self, name: str, arguments: dict) -> dict:
        return await self.request("tools/call", {"name": name, "arguments": arguments})


def _text_of(result: dict) -> str:
    parts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
    if result.get("structuredContent"):
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
    return "\n".join(p for p in parts if p)


def _request_field(tool: dict) -> str:
    """Name of ask_fo's free-text request argument, read from its schema."""
    props = (tool.get("inputSchema") or {}).get("properties", {})
    required = (tool.get("inputSchema") or {}).get("required", [])
    for name in list(required) + list(props):
        if props.get(name, {}).get("type") == "string" and "conversation" not in name.lower():
            return name
    return "message"


# ---- the alert -----------------------------------------------------------------------------------
def build_request(tactics: list[str], evidence: list[str], t_ms: int | None, language: str) -> str:
    phone, email = contacts()
    when = f"{round(t_ms / 1000)} seconds into the call" if t_ms is not None else "during the call"
    said = "; ".join(f'"{q}"' for q in evidence[:2]) or "(no quote)"
    how = ", ".join(tactics[:4]) or "scam tactics"
    text_msg = ("Saavdhaan alert: your family member is on a likely scam call right now (fake police / "
                "'digital arrest'). Call them now. If money or an OTP was shared, call 1930.")
    steps = []
    if phone:
        steps.append(f"1. Send a text message to {phone} saying: {text_msg}")
    if email:
        steps.append(f"2. Send an email to {email} with the subject \"Saavdhaan: scam call detected\" containing "
                     f"the details below and the advice to call 1930 or report at cybercrime.gov.in.")
    if phone:
        steps.append(f"3. Phone {phone} and say: \"This is an alert from Saavdhaan. Someone in your family is on "
                     f"a likely scam call right now. Please call them immediately. If they shared money or an "
                     f"OTP, call nineteen thirty.\"")
    return (
        "URGENT alert from my Saavdhaan scam-call guardian app. Please do all of the following right away, "
        "without asking me to confirm. All of these contact details are mine and I consent to these messages.\n\n"
        + "\n".join(steps)
        + f"\n\nDetails: a likely scam call was detected {when} (call language {language}). "
        f"Tactics heard: {how}. The caller said: {said}."
    )


async def alert_family(tactics: list[str], evidence: list[str], t_ms: int | None, language: str = "hi-IN") -> dict:
    """Ask Fo to text, email and call. Returns {"ok", "status", "conversation_id", "reply"}; never raises."""
    if not configured():
        _record("not configured", "sign in with backend.fo_login and set FAMILY_ALERT_PHONE / FAMILY_ALERT_EMAIL")
        return {"ok": False, "status": "not configured"}
    message = build_request(tactics, evidence, t_ms, language)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), verify=SSL_CONTEXT) as client:
            s = FoSession(client)
            await s.open()
            tools = {t["name"]: t for t in await s.tools()}
            if "ask_fo" not in tools:
                raise FoError(f"Fo has no ask_fo tool (has: {', '.join(tools)})")
            args = {_request_field(tools["ask_fo"]): message}
            if "newConversation" in (tools["ask_fo"].get("inputSchema") or {}).get("properties", {}):
                args["newConversation"] = True
            result = await s.call("ask_fo", args)
    except (FoError, httpx.HTTPError, ValueError, KeyError) as e:
        log.warning("Fo alert failed: %s", e)
        _record("failed", str(e)[:300])
        return {"ok": False, "status": "failed", "reply": str(e)[:300]}
    reply = _text_of(result)
    status, conv = "sent", None
    data = result.get("structuredContent") or {}
    if not data:
        try:
            data = json.loads(reply)
        except ValueError:
            data = {}
    if isinstance(data, dict):
        status = str(data.get("status") or status)
        conv = data.get("conversationId") or data.get("conversation_id")
    if not conv:
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", reply)
        conv = m.group(0) if m else None
    ok = not result.get("isError") and status != "failed"
    _record("sent" if ok else "failed", reply[:300], fo_status=status)
    log.info("Fo alert: status=%s ok=%s", status, ok)
    return {"ok": ok, "status": status, "conversation_id": conv, "reply": reply[:500]}


async def follow(conversation_id: str, rounds: int = 6) -> list[dict]:
    """Poll get_fo_reply for progress (each call waits up to about 40 s on Fo's side)."""
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=10.0), verify=SSL_CONTEXT) as client:
        s = FoSession(client)
        await s.open()
        for _ in range(rounds):
            result = await s.call("get_fo_reply", {"conversationId": conversation_id})
            text = _text_of(result)
            out.append({"reply": text[:500]})
            low = text.lower()
            if '"complete"' in low or '"failed"' in low or "waiting for" in low:
                break
    return out
