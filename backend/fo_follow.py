"""Follow Fo's progress on the latest Saavdhaan alert until it is complete or failed.

Run:  .\\.venv\\Scripts\\python.exe -m backend.fo_follow
Prints each progress update from Fo (get_fo_reply waits up to 40 s per call on Fo's side).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

import httpx
from dotenv import load_dotenv

from backend.fo_client import ROOT, SSL_CONTEXT, FoSession, _text_of


async def main(rounds: int = 12) -> int:
    load_dotenv(ROOT / ".env")
    async with httpx.AsyncClient(timeout=httpx.Timeout(75.0, connect=10.0), verify=SSL_CONTEXT) as client:
        s = FoSession(client)
        await s.open()
        convs = _text_of(await s.call("list_fo_conversations", {}))
        # Fo lists one conversation per line: "Title (channel, time) – <uuid>", newest first.
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", convs)
        conv_id = m.group(0) if m else None
        print("latest:", convs.splitlines()[0] if convs else "(none)", flush=True)
        if not conv_id:
            print("Could not find the latest conversation. Raw list:\n" + convs[:800])
            return 1
        print(f"following the latest Fo conversation", flush=True)
        for i in range(rounds):
            text = _text_of(await s.call("get_fo_reply", {"conversationId": conv_id, "waitSeconds": 40}))
            print(f"[{i + 1}] {text[:600]}\n", flush=True)
            low = text.lower()
            if '"status": "complete"' in low or '"status":"complete"' in low or '"status": "failed"' in low \
                    or '"status":"failed"' in low or "waiting for your" in low:
                break
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
