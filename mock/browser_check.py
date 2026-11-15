"""Drive the call screen in a real Chrome and check the whole flow, with screenshots.

Needs the server already running (mock or real). From the project root:
    .\\.venv\\Scripts\\python.exe mock\\browser_check.py                       # mock, scam call
    .\\.venv\\Scripts\\python.exe mock\\browser_check.py --scenario drop       # also: normal, error
    .\\.venv\\Scripts\\python.exe mock\\browser_check.py --scenario real --audio-file eval\\audio\\clean\\x.wav --duration 70

Chrome runs headless at 1920x1080 with a fake microphone (a beep, or --audio-file played as the mic),
so there is no permission prompt. Clicks are real mouse events, so the autoplay policy is the real one.
Checks: transcript, meter, tactics, warning audio, alert, summary, every WebSocket frame the page sent
(binary frames must be 1,024 bytes), console errors and warnings, and page overflow.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx
import websockets

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

# Seconds of call to let play before pressing Stop (at speed 1), and what to expect.
SCENARIOS = {
    "scam": {"run_s": 46, "warning": True, "lines": 11, "tactics": 6},
    "normal": {"run_s": 27, "warning": False, "lines": 7, "tactics": 0},
    "error": {"run_s": 46, "warning": True, "lines": 11, "tactics": 6, "error_text": "429"},
    "drop": {"run_s": None, "drop": True},
    "real": {"run_s": None},
}

SNAPSHOT = """(() => {
  const q = (s) => document.querySelector(s);
  const all = (s) => Array.from(document.querySelectorAll(s));
  return JSON.stringify({
    phase: document.body.dataset.phase,
    level: document.body.dataset.level,
    headline: q('#headline').textContent,
    status: q('#status-text').textContent,
    clock: q('#clock').textContent,
    score: Number(q('#score').textContent),
    lines: all('#transcript .line').length,
    marks: all('#transcript mark').map((m) => m.textContent),
    lit: all('#tactics li.lit').map((li) => li.textContent),
    warning: !q('#warning').hidden,
    warningTime: q('#warning-time').textContent,
    audio: q('#warning').dataset.audio,
    alert: !q('#alert').hidden,
    alertText: q('#alert').hidden ? '' : q('#alert').innerText,
    summary: !q('#summary').hidden,
    summaryText: q('#summary').hidden ? '' : q('#summary').innerText,
    errors: all('#errors .err').map((e) => e.innerText),
    demoNote: q('.demo-note').innerText,
    stats: window.saavdhaanStats,
    overflowX: document.documentElement.scrollWidth > window.innerWidth,
    anekLoaded: Array.from(document.fonts).some((f) => f.family.includes('Anek') && f.status === 'loaded'),
  });
})()"""


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.listeners = []

    async def run(self) -> None:
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self.pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(str(msg["error"])))
                    else:
                        fut.set_result(msg.get("result", {}))
            else:
                for fn in self.listeners:
                    fn(msg.get("method"), msg.get("params", {}))

    async def send(self, method: str, **params):
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = fut
        await self.ws.send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        return await asyncio.wait_for(fut, 30)

    async def eval(self, expression: str, await_promise: bool = False):
        r = await self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_chrome() -> str:
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    sys.exit("Chrome or Edge not found; edit CHROME_PATHS in mock/browser_check.py.")


async def click(cdp: CDP, selector: str) -> None:
    rect = await cdp.eval(
        f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e || e.hidden) return null;"
        f" const r = e.getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2, r.width]; }})()")
    if not rect or not rect[2]:
        raise RuntimeError(f"{selector} is not visible, cannot click it")
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        await cdp.send("Input.dispatchMouseEvent", type=kind, x=rect[0], y=rect[1], button="left", clickCount=1)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/")
    ap.add_argument("--scenario", default="scam", choices=sorted(SCENARIOS))
    ap.add_argument("--speed", type=float, default=1.0, help="mock replay speed")
    ap.add_argument("--audio-file", help="WAV to use as the microphone (needed for --scenario real)")
    ap.add_argument("--duration", type=float, default=60, help="seconds before Stop, for --scenario real")
    ap.add_argument("--shots", default=str(Path(tempfile.gettempdir()) / "saavdhaan_shots"))
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    spec = SCENARIOS[args.scenario]
    url = args.url
    if args.scenario != "real":
        url += ("&" if "?" in url else "?") + f"scenario={args.scenario}&speed={args.speed:g}"
    run_s = spec["run_s"] / args.speed if spec["run_s"] else (args.duration if args.scenario == "real" else None)
    shots_dir = Path(args.shots) / args.scenario
    shots_dir.mkdir(parents=True, exist_ok=True)

    port = free_port()
    profile = tempfile.mkdtemp(prefix="saavdhaan_chrome_")
    cmd = [find_chrome(), f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
           "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
           "--window-size=1920,1080", "--no-first-run", "--no-default-browser-check",
           # A headed window covered by other windows counts as hidden: Chrome then defers media playback
           # (the warning never starts) and slows timers. Keep it "visible" while the check runs.
           "--disable-features=Translate,CalculateNativeWinOcclusion", "--disable-backgrounding-occluded-windows",
           "--disable-renderer-backgrounding", "--disable-background-timer-throttling", "about:blank"]
    if not args.headed:
        cmd.insert(1, "--headless=new")
    if args.audio_file:
        cmd.insert(1, f"--use-file-for-fake-audio-capture={Path(args.audio_file).resolve()}%noloop")
    chrome = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    console: list[str] = []
    exceptions: list[str] = []
    frames: list[tuple[float, int]] = []
    text_frames: list[str] = []
    received: Counter = Counter()
    ws_closed: list[float] = []
    milestones: dict[str, float] = {}
    shot_times: list[tuple[str, float]] = []
    t_click = 0.0
    scores: list[float] = []
    t0 = time.monotonic()

    def since() -> float:
        return round(time.monotonic() - t0, 2)

    def on_event(method, p):
        if method == "Runtime.consoleAPICalled":
            parts = [str(a.get("value", a.get("description", ""))) for a in p.get("args", [])]
            console.append(f"console.{p.get('type')}: {' '.join(parts)}")
        elif method == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            exceptions.append(f"{d.get('text')} {d.get('exception', {}).get('description', '')}")
        elif method == "Log.entryAdded":
            e = p.get("entry", {})
            console.append(f"log.{e.get('level')} [{e.get('source')}]: {e.get('text')} {e.get('url', '')}")
        elif method == "Network.webSocketFrameSent":
            r = p.get("response", {})
            if r.get("opcode") == 2:
                frames.append((p.get("timestamp", 0.0), len(base64.b64decode(r.get("payloadData", "")))))
            else:
                text_frames.append(r.get("payloadData", ""))
        elif method == "Network.webSocketFrameReceived":
            try:
                received[json.loads(p["response"]["payloadData"]).get("type")] += 1
            except Exception:
                received["<unparsed>"] += 1
        elif method == "Network.webSocketClosed":
            ws_closed.append(since())

    try:
        async with httpx.AsyncClient() as http:
            for _ in range(100):
                try:
                    targets = (await http.get(f"http://127.0.0.1:{port}/json/list")).json()
                    page = next(t for t in targets if t.get("type") == "page")
                    break
                except Exception:
                    await asyncio.sleep(0.1)
            else:
                print("Chrome did not start its debugging port.")
                return 2
            try:
                mock_before = (await http.get(args.url.split("?")[0].rstrip("/") + "/mock/stats")).json()
            except Exception:
                mock_before = None

        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            cdp = CDP(ws)
            cdp.listeners.append(on_event)
            reader = asyncio.create_task(cdp.run())
            for domain in ("Page", "Runtime", "Log", "Network"):
                await cdp.send(f"{domain}.enable")
            await cdp.send("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1,
                           mobile=False)
            await cdp.send("Page.navigate", url=url)
            for _ in range(100):
                if await cdp.eval("document.readyState") == "complete":
                    break
                await asyncio.sleep(0.1)
            await cdp.eval("document.fonts.ready.then(() => true)", await_promise=True)

            async def shot(name: str) -> None:
                shot_times.append((name, round(time.monotonic() - t_click, 2) if t_click else 0.0))
                data = (await cdp.send("Page.captureScreenshot", format="png"))["data"]
                (shots_dir / f"{name}.png").write_bytes(base64.b64decode(data))

            async def snap() -> dict:
                return json.loads(await cdp.eval(SNAPSHOT))

            await shot("00-ready")
            await click(cdp, "#start")
            t_start = t_click = time.monotonic()
            pending: list[tuple[float, str]] = []
            stopped_at = None
            alert_text = ""
            deadline = t_start + (run_s or args.duration) + 40
            last = {}
            while time.monotonic() < deadline:
                s = await snap()
                last = s
                now = time.monotonic()
                scores.append(s["score"])

                def reach(name: str, cond: bool, shot_name: str | None = None, delay: float = 0.0) -> None:
                    if cond and name not in milestones:
                        milestones[name] = round(now - t_start, 2)
                        if shot_name:
                            pending.append((now + delay, shot_name))

                reach("listening", s["phase"] == "listening")
                reach("first_transcript", s["lines"] >= 1, "01-listening", 0.8)
                reach("first_highlight", len(s["marks"]) >= 1)
                reach("caution", s["level"] == "caution", "02-caution", 1.4)
                reach("danger", s["level"] == "danger", "03-danger", 1.6)
                reach("warning_shown", s["warning"], "04-warning", 0.7)
                reach("warning_audio_playing", s["audio"] == "playing")
                reach("warning_audio_played", s["audio"] == "played")
                reach("alert_shown", s["alert"], "05-alert", 1.0)
                reach("summary_shown", s["summary"], "07-summary", 0.7)
                reach("ended", s["phase"] == "ended")
                reach("dropped", s["phase"] == "dropped", "drop", 0.6)
                reach("not_listening_shown", s["headline"] == "Not listening to the call", "not-listening", 0.5)
                for due, name in [p for p in pending if p[0] <= now]:
                    pending.remove((due, name))
                    await shot(name)

                if stopped_at is None and run_s and now - t_start >= run_s and s["phase"] in ("listening", "connecting"):
                    await shot("06-before-stop")
                    await click(cdp, "#stop")
                    stopped_at = round(now - t_start, 2)
                    milestones["stop_clicked"] = stopped_at
                if s["alert"]:
                    alert_text = s["alertText"]
                finished = "dropped" in milestones or ("ended" in milestones and "summary_shown" in milestones)
                if finished and not pending:
                    break
                await asyncio.sleep(0.15)
            await asyncio.sleep(0.5)
            last = await snap()
            reader.cancel()
        async with httpx.AsyncClient() as http:
            try:
                mock_after = (await http.get(args.url.split("?")[0].rstrip("/") + "/mock/stats")).json()
            except Exception:
                mock_after = None
    finally:
        chrome.terminate()
        try:
            chrome.wait(5)
        except Exception:
            chrome.kill()
        shutil.rmtree(profile, ignore_errors=True)

    # ---- Report ------------------------------------------------------------------------------
    sizes = Counter(n for _, n in frames)
    fps = None
    if len(frames) > 1 and frames[-1][0] > frames[0][0]:
        fps = round((len(frames) - 1) / (frames[-1][0] - frames[0][0]), 2)
    gaps = [(round(frames[i - 1][0] - frames[0][0], 2), round(frames[i][0] - frames[i - 1][0], 3))
            for i in range(1, len(frames)) if frames[i][0] - frames[i - 1][0] > 0.1]
    distinct_scores = len(set(round(x) for x in scores))
    checks: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    check("frames sent", len(frames) > 0, f"{len(frames)} binary frames")
    check("every frame is 1,024 bytes", sizes and set(sizes) == {1024}, f"sizes {dict(sizes)}")
    check("real-time pace (~31.25 frames/s)", fps is not None and 28 <= fps <= 34, f"{fps} frames/s")
    starts = [t for t in text_frames if '"start"' in t]
    check("start message sent", starts and json.loads(starts[0]).get("language") == "hi-IN", starts[:1])
    if run_s:
        check("stop message sent", any('"stop"' in t for t in text_frames), "")
    check("console clean", not console and not exceptions, console + exceptions)
    check("no horizontal overflow at 1920x1080", not last.get("overflowX"), "")
    check("mode line shown", "Speakerphone mode" in (last.get("demoNote") or ""), last.get("demoNote"))
    check("Anek Devanagari font loaded", last.get("anekLoaded"), "falls back to Nirmala UI if not")
    if spec.get("lines") is not None:
        check("transcript lines", last["lines"] >= spec["lines"], f"{last['lines']} lines")
    if spec.get("tactics") is not None:
        check("tactics lit", len(last["lit"]) == spec["tactics"], last["lit"])
    if spec.get("warning"):
        check("evidence highlighted", len(last["marks"]) >= 3, last["marks"])
        check("meter reached danger", "danger" in milestones, f"at {milestones.get('danger')} s")
        check("meter moved smoothly", distinct_scores >= 25, f"{distinct_scores} distinct displayed values")
        check("warning shown with call time", "warning_shown" in milestones and "into the call" in last["warningTime"],
              last["warningTime"])
        check("warning audio played", "warning_audio_played" in milestones,
              f"playing at {milestones.get('warning_audio_playing')} s, ended at {milestones.get('warning_audio_played')} s")
        check("alert shown", "alert_shown" in milestones and bool(alert_text.strip()),
              alert_text.replace("\n", " | "))
    elif spec.get("warning") is False:
        check("no warning on a normal call", "warning_shown" not in milestones and last["level"] == "safe", last["level"])
    if run_s:
        check("summary shown with 1930", "summary_shown" in milestones and "1930" in last["summaryText"], "")
        check("call ended cleanly", last["phase"] == "ended", last["phase"])
    if spec.get("error_text"):
        check("server error shown", any(spec["error_text"] in e for e in last["errors"]), last["errors"])
    elif not spec.get("drop"):
        check("no error banners", not last["errors"], last["errors"])
    if spec.get("drop"):
        check("dropped connection shown", last["phase"] == "dropped" and any("Connection lost" in e for e in last["errors"]),
              last["errors"])
    if mock_after and mock_before is not None and mock_after.get("calls", 0) > mock_before.get("calls", 0):
        check("mock received only 1,024-byte frames", mock_after.get("bad_frames") == 0, mock_after)

    print(f"URL: {url}")
    print(f"Screenshots: {shots_dir}")
    print("Milestones (s after Start):", json.dumps(milestones))
    print("Events received:", dict(received))
    print("Page stats:", json.dumps(last.get("stats")))
    print(f"Frame gaps over 100 ms: {len(gaps)}, adding up to {sum(g for _, g in gaps):.2f} s;"
          f" first: {gaps[:8]}")
    print("Screenshots at (s after Start):", shot_times)
    if mock_after:
        print("Mock saw:", json.dumps(mock_after))
    print("Final headline:", last.get("headline"), "| phase:", last.get("phase"), "| level:", last.get("level"))
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail not in ("", None, []) else ""))
    failed = [c for c in checks if not c[1]]
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
