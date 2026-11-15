"""One-time sign-in to Wajo Fo for the Saavdhaan server (OAuth 2.1 + PKCE, as Fo's MCP server requires).

Run:  .\\.venv\\Scripts\\python.exe -m backend.fo_login
A browser opens on Wajo's sign-in page; log in and approve. The tokens are saved to .fo_tokens.json in
the project root (gitignored) and refreshed automatically by backend/fo_client.py afterwards.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / ".fo_tokens.json"
ISSUER = "https://mcp.api.wajo.ai"
RESOURCE = "https://mcp.api.wajo.ai/fo"
PORT = 8766
REDIRECT = f"http://127.0.0.1:{PORT}/callback"


def main() -> int:
    meta = httpx.get(f"{ISSUER}/.well-known/oauth-authorization-server", timeout=15).json()
    reg = httpx.post(meta["registration_endpoint"], timeout=15, json={
        "client_name": "Saavdhaan scam-call guardian",
        "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": "mcp",
    })
    reg.raise_for_status()
    client_id = reg.json()["client_id"]

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = meta["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "scope": "mcp",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "resource": RESOURCE,
    })

    result: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != "/callback":
                self.send_response(404); self.end_headers(); return
            got = {k: v[0] for k, v in q.items()}
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if got.get("state") != state:  # an old tab or an old link: ignore it and keep waiting
                msg = "This sign-in link is out of date. Use the newest link from the terminal."
                print(f"Ignored a callback from an old sign-in link (state {got.get('state')!r}).", flush=True)
            else:
                result.update(got)
                msg = "Saavdhaan is now connected to Fo. You can close this tab." if "code" in got else \
                    f"Sign-in did not complete: {got.get('error_description') or got.get('error')}"
                done.set()
            self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'><h2>{msg}</h2></body></html>".encode())

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Opening Wajo sign-in in your browser. If it does not open, visit:\n" + url, flush=True)
    webbrowser.open(url)
    if not done.wait(timeout=600):
        print("Timed out waiting for the sign-in (10 minutes).")
        return 1
    server.shutdown()
    if "code" not in result or result.get("state") != state:
        print(f"Sign-in failed: {result}")
        return 1

    tok = httpx.post(meta["token_endpoint"], timeout=20, data={
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT,
        "client_id": client_id, "code_verifier": verifier, "resource": RESOURCE,
    })
    if tok.status_code != 200:
        print(f"Token exchange failed: HTTP {tok.status_code} {tok.text[:300]}")
        return 1
    t = tok.json()
    TOKENS.write_text(json.dumps({
        "client_id": client_id,
        "token_endpoint": meta["token_endpoint"],
        "access_token": t["access_token"],
        "refresh_token": t.get("refresh_token"),
        "expires_at": time.time() + float(t.get("expires_in", 3600)) - 60,
    }, indent=2), encoding="utf-8")
    print(f"Connected to Fo. Tokens saved to {TOKENS} (keep this file private; it is gitignored).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
