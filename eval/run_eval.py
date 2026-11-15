"""Stream each synthetic call to /ws/call at real-time pace, record every event, and score the run.

Run from the project root while the backend (or the mock) listens on port 8000:
    .\\.venv\\Scripts\\python.exe -m eval.run_eval                        # all files in eval/audio/manifest.json
    .\\.venv\\Scripts\\python.exe -m eval.run_eval --variant clean         # clean audio only
    .\\.venv\\Scripts\\python.exe -m eval.run_eval --only scam_cbi_digital_arrest

One call at a time: connect, send "start", wait for status "listening", send the WAV in 1,024-byte
frames at real-time pace, send "stop", read until status "ended". Writes eval/results.json (every event,
audio_b64 replaced by its length) and eval/RESULTS.md. If GET /health says the server is the mock,
the write-up is titled as a mock run, because the mock replays a fixed script and ignores the audio.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import numpy as np
import soundfile as sf
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.contract import FRAME_BYTES, SAMPLE_RATE  # noqa: E402

FRAME_S = FRAME_BYTES / (SAMPLE_RATE * 2)  # 0.032 s
IST = timezone(timedelta(hours=5, minutes=30))
START_MSG = {"type": "start", "language": "hi-IN", "warn_language": "hi-IN"}


def load_pcm(path: Path) -> bytes:
    data, rate = sf.read(str(path), dtype="int16", always_2d=True)
    if rate != SAMPLE_RATE or data.shape[1] != 1:
        raise ValueError(f"{path.name}: need {SAMPLE_RATE} Hz mono, got {rate} Hz x{data.shape[1]}")
    return data[:, 0].astype("<i2").tobytes()


class Call:
    """One streamed call and everything the server sent back."""

    def __init__(self, entry: dict, pcm: bytes):
        self.entry, self.pcm = entry, pcm
        self.events: list[dict] = []
        self.t_start = 0.0
        self.t_stream: float | None = None
        self.t_stream_end: float | None = None
        self.bytes_sent = 0
        self.listening = asyncio.Event()
        self.ended = asyncio.Event()
        self.notes: list[str] = []

    def now(self) -> float:
        return asyncio.get_running_loop().time()

    async def read(self, ws) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    self.notes.append(f"unexpected binary message ({len(raw)} bytes)")
                    continue
                try:
                    ev = json.loads(raw)
                except ValueError:
                    self.notes.append(f"non-JSON text: {raw[:80]!r}")
                    continue
                rec = {"recv_s": round(self.now() - self.t_start, 3),
                       "stream_s": round(self.now() - self.t_stream, 3) if self.t_stream else None,
                       "audio_sent_ms": self.bytes_sent * 1000 // (SAMPLE_RATE * 2), **ev}
                if "audio_b64" in rec:
                    rec["audio_b64_chars"] = len(rec.pop("audio_b64") or "")
                self.events.append(rec)
                if ev.get("type") == "status" and ev.get("state") == "listening":
                    self.listening.set()
                if ev.get("type") == "status" and ev.get("state") == "ended":
                    self.ended.set()
        except ConnectionClosed as e:
            self.notes.append(f"connection closed: code {e.rcvd.code if e.rcvd else None}")

    async def run(self, url: str, listen_timeout: float, end_timeout: float, speed: float) -> None:
        async with connect(url, max_size=None, open_timeout=15, ping_interval=20, ping_timeout=60) as ws:
            self.t_start = self.now()
            reader = asyncio.create_task(self.read(ws))
            await ws.send(json.dumps(START_MSG))
            try:
                await asyncio.wait_for(self.listening.wait(), listen_timeout)
            except asyncio.TimeoutError:
                self.notes.append(f"no 'listening' status within {listen_timeout:.0f} s; streamed anyway")
            pcm = self.pcm + b"\x00" * (-len(self.pcm) % FRAME_BYTES)
            self.t_stream = self.now()
            for i in range(len(pcm) // FRAME_BYTES):
                delay = self.t_stream + i * FRAME_S / speed - self.now()
                if delay > 0:
                    await asyncio.sleep(delay)
                if reader.done():
                    self.notes.append(f"server closed the socket after {self.bytes_sent // 32000:.0f} s of audio")
                    break
                await ws.send(pcm[i * FRAME_BYTES:(i + 1) * FRAME_BYTES])
                self.bytes_sent += FRAME_BYTES
            self.t_stream_end = self.now()
            if not reader.done():
                await ws.send(json.dumps({"type": "stop"}))
                try:
                    await asyncio.wait_for(self.ended.wait(), end_timeout)
                except asyncio.TimeoutError:
                    self.notes.append(f"no 'ended' status within {end_timeout:.0f} s of stop")
            await ws.close()
            try:
                await asyncio.wait_for(reader, 5)
            except asyncio.TimeoutError:
                reader.cancel()

    def result(self) -> dict:
        of = lambda kind: [e for e in self.events if e.get("type") == kind]  # noqa: E731
        transcripts, warnings, risks = of("transcript"), of("warning"), of("risk")
        latencies = [e["latency_ms"] for e in transcripts if isinstance(e.get("latency_ms"), (int, float))]
        warn = warnings[0] if warnings else None
        before = [e for e in transcripts if warn and e["recv_s"] <= warn["recv_s"]]
        summary = next(iter(of("summary")), None)
        audio_s = len(self.pcm) / (SAMPLE_RATE * 2)
        streamed = (self.t_stream_end - self.t_stream) if self.t_stream and self.t_stream_end else None
        return {
            "id": self.entry["id"], "label": self.entry["label"], "variant": self.entry["variant"],
            "path": self.entry["path"], "audio_s": round(audio_s, 2),
            "warned": warn is not None,
            "warning_t_s": round(warn["t_ms"] / 1000, 2) if warn and isinstance(warn.get("t_ms"), (int, float)) else None,
            "warning_wall_s": warn["stream_s"] if warn else None,
            "warning_after_sentence": before[-1]["text"] if before else None,
            "warnings_sent": len(warnings),
            "alerts_sent": len(of("alert")),
            "peak_score": max((e.get("score", 0) for e in risks), default=None),
            "peak_level": max((e.get("level") for e in risks), key=["safe", "caution", "danger"].index, default=None),
            "risk_sources": sorted({e.get("source") for e in risks if e.get("source")}),
            "transcripts": len(transcripts),
            "latency_ms": latencies,
            "summary": {k: v for k, v in (summary or {}).items() if k not in ("recv_s", "stream_s", "audio_sent_ms")} or None,
            "errors": [e.get("message") for e in of("error")],
            "ended_cleanly": self.ended.is_set(),
            "listening_wait_s": next((e["recv_s"] for e in self.events
                                      if e.get("type") == "status" and e.get("state") == "listening"), None),
            "stream_realtime_factor": round(streamed / audio_s, 3) if streamed and audio_s else None,
            "notes": self.notes,
            "events": self.events,
        }


def health(url: str) -> dict:
    parts = urlsplit(url)
    scheme = "https" if parts.scheme == "wss" else "http"
    try:
        r = httpx.get(f"{scheme}://{parts.netloc}/health", timeout=5)
        return r.json() if r.status_code == 200 else {"http_status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"unreachable": repr(e)}


def aggregate(results: list[dict]) -> dict:
    out = {}
    for variant in sorted({r["variant"] for r in results}):
        rs = [r for r in results if r["variant"] == variant]
        scams = [r for r in rs if r["label"] == "scam"]
        normals = [r for r in rs if r["label"] == "normal"]
        lat = [x for r in rs for x in r["latency_ms"]]
        out[variant] = {
            "scams_caught": sum(r["warned"] for r in scams), "scams": len(scams),
            "false_alarms": sum(r["warned"] for r in normals), "normals": len(normals),
            "warning_t_s": {r["id"]: r["warning_t_s"] for r in scams},
            "median_transcript_latency_ms": statistics.median(lat) if lat else None,
            "transcript_latency_samples": len(lat),
            "calls_with_errors": sum(bool(r["errors"]) for r in rs),
        }
    return out


def fmt_s(x) -> str:
    return "not warned" if x is None else f"{x:.1f} s"


def write_markdown(path: Path, meta: dict, results: list[dict], agg: dict) -> None:
    variants = list(agg)
    ids = list(dict.fromkeys(r["id"] for r in results))
    by = {(r["id"], r["variant"]): r for r in results}
    label = {r["id"]: r["label"] for r in results}
    lines = []
    if meta["mock"]:
        lines += ["# MOCK RUN: pipeline check only, not results", "",
                  "The server reported itself as the mock (`/health` has `mock: true`). The mock replays a fixed "
                  "script and ignores the audio, so nothing below measures Saavdhaan. Do not quote these numbers.", ""]
    else:
        lines += ["# Saavdhaan smoke test", ""]
    n_scam = sum(1 for i in ids if label[i] == "scam")
    n_norm = len(ids) - n_scam
    lines += [
        f"Run {meta['started_ist']} IST against `{meta['url']}`, {len(ids)} synthetic calls "
        f"({n_scam} scam, {n_norm} normal) x {len(variants)} audio version(s): {', '.join(variants)}.",
        "",
        f"**Sample size: {len(ids)} calls. This is a smoke test, not a benchmark.** The calls were scripted "
        "for this test and voiced with Gnani Timbre text-to-speech, so they are cleaner and more predictable "
        "than real phone calls. One run, no repeats, no confidence intervals.",
        "",
    ]
    llm = (meta.get("health") or {}).get("llm_judge") or {}
    if llm and llm.get("state") != "working":
        lines += [f"**Risk scoring in this run: keyword rules only.** The LLM judge was `{llm.get('state')}` "
                  f"({str(llm.get('detail', '')).strip()[:120]}), so every score came from the keyword engine.", ""]
    if meta["speed"] != 1:
        lines += [f"Audio was streamed at {meta['speed']}x real time, so latency and timing are not representative.", ""]
    lines += ["| Audio | Scams warned | False alarms on normal calls | Median transcript latency |",
              "|---|---|---|---|"]
    for v in variants:
        a = agg[v]
        med = "n/a" if a["median_transcript_latency_ms"] is None else \
            f"{a['median_transcript_latency_ms']:.0f} ms ({a['transcript_latency_samples']} sentences)"
        lines.append(f"| {v} | {a['scams_caught']} / {a['scams']} | {a['false_alarms']} / {a['normals']} | {med} |")
    lines += ["", "## Time from call start to the spoken warning, scam calls", "",
              "Seconds of call audio before the warning event (`t_ms` in the event). The call length is in brackets.",
              "", "| Scam call | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for i in ids:
        if label[i] == "scam":
            cells = [f"{fmt_s(by[(i, v)]['warning_t_s'])} (of {by[(i, v)]['audio_s']:.0f} s)" if (i, v) in by else "-"
                     for v in variants]
            lines.append(f"| {i} | " + " | ".join(cells) + " |")
    lines += ["", "## Peak risk per call", "", "| Call | Label | " + " | ".join(variants) + " |",
              "|---|---|" + "---|" * len(variants)]
    for i in ids:
        cells = []
        for v in variants:
            r = by.get((i, v))
            cells.append("-" if r is None else
                         f"{r['peak_score']} {r['peak_level']}{' (warned)' if r['warned'] else ''}")
        lines.append(f"| {i} | {label[i]} | " + " | ".join(cells) + " |")
    problems = [(r["id"], r["variant"], m) for r in results for m in r["errors"] + r["notes"]]
    if problems:
        lines += ["", "## Errors and notes during the run", ""]
        lines += [f"- {i} ({v}): {m}" for i, v, m in problems]
    lines += ["", "## How this was measured", "",
              "- `eval/run_eval.py` streams each WAV to `/ws/call` in 1,024-byte frames at real-time pace, one call "
              "at a time, and records every event in `eval/results.json`.",
              "- A scam counts as caught if the server sent a `warning` event during the call. A false alarm is a "
              "`warning` on a normal call.",
              "- Transcript latency is the `latency_ms` the backend reports on each `transcript` event (from Gnani "
              "Prisma), not measured by this script.",
              "- Phone audio: street noise and mains hum added, band-limited to 300-3400 Hz, mu-law at 8 kHz, back to "
              "16 kHz. See `eval/make_audio.py`.",
              f"- Server `/health`: `{json.dumps(meta['health'], ensure_ascii=False)}`"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main_async(args) -> int:
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    base = Path(args.manifest).parent
    entries = [f for f in manifest["files"]
               if (args.variant == "all" or f["variant"] == args.variant) and (not args.only or f["id"] in args.only)]
    entries.sort(key=lambda f: (f["variant"] != "clean", f["label"] != "scam", f["id"]))
    if not entries:
        print("no matching files in the manifest")
        return 2
    url = args.url + (("&" if "?" in args.url else "?") + args.query if args.query else "")
    meta = {"started_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M"), "url": url, "speed": args.speed,
            "health": health(args.url), "manifest": str(Path(args.manifest)), "frame_bytes": FRAME_BYTES}
    meta["mock"] = bool(meta["health"].get("mock"))
    if "unreachable" in meta["health"]:
        print(f"backend not reachable: {meta['health']['unreachable']}")
        return 1
    print(f"server /health: {meta['health']}")

    results = []
    for n, entry in enumerate(entries, 1):
        call = Call(entry, load_pcm(base / entry["path"]))
        print(f"[{n}/{len(entries)}] {entry['variant']}/{entry['id']} ({entry['label']}, "
              f"{len(call.pcm) / 32000:.0f} s) ...", flush=True)
        try:
            await call.run(url, args.listen_timeout, args.end_timeout, args.speed)
        except Exception as e:  # noqa: BLE001  record and carry on with the next call
            call.notes.append(f"client error: {e!r}")
        r = call.result()
        results.append(r)
        print(f"    warned={r['warned']} at {fmt_s(r['warning_t_s'])}, peak {r['peak_score']} {r['peak_level']}, "
              f"{r['transcripts']} sentences, errors {len(r['errors'])}, notes {r['notes']}", flush=True)
        if n < len(entries):
            await asyncio.sleep(args.gap)

    agg = aggregate(results)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta["finished_ist"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    (out_dir / "results.json").write_text(json.dumps({"meta": meta, "aggregate": agg, "calls": results},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out_dir / "RESULTS.md", meta, results, agg)
    print(json.dumps(agg, indent=2))
    print(f"wrote {out_dir / 'results.json'} and {out_dir / 'RESULTS.md'}")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://localhost:8000/ws/call")
    ap.add_argument("--query", default="", help="extra query string, e.g. scenario=normal for the mock")
    ap.add_argument("--manifest", default=str(HERE / "audio" / "manifest.json"))
    ap.add_argument("--variant", choices=("clean", "phone", "all"), default="all")
    ap.add_argument("--only", nargs="*", help="call ids to run (default: all)")
    ap.add_argument("--out-dir", default=str(HERE))
    ap.add_argument("--speed", type=float, default=1.0, help="stream speed; keep 1 for real measurements")
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between calls")
    ap.add_argument("--listen-timeout", type=float, default=20.0)
    ap.add_argument("--end-timeout", type=float, default=30.0)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
