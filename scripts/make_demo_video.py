"""Record the live demo and turn it into a captioned, narrated video (no ffmpeg needed).

    python scripts/make_demo_video.py all --providers anthropic,gemini
    python scripts/make_demo_video.py record     # drive the real app with a model, take screenshots
    python scripts/make_demo_video.py narrate    # speak the script with Windows' built-in voice
    python scripts/make_demo_video.py assemble   # stitch screenshots, voice and captions into a .webm

``record`` starts the server (``run_api.py --demo --llm``), then plays the whole story through a headless
Chrome: a customer pays, the monitor reviews, a model investigates, an analyst and a risk officer
approve a freeze, the customer's next payment is refused, the auditor reads the results. The screens
are the real ones; only the pacing is edited. ``assemble`` renders the video inside Chrome (a canvas,
Web Audio and MediaRecorder), so the only requirements are Windows, Chrome and the project's own
dependencies (``pip install websockets``). Output goes to ``presentation/demo/``.
"""

import argparse
import asyncio
import base64
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "presentation" / "demo"
SHOTS = OUT / "shots"
AUDIO = OUT / "audio"
CHROME = os.environ.get("CHROME", "C:/Program Files/Google/Chrome/Application/chrome.exe")
API_PORT, DEBUG_PORT, FILE_PORT = 8771, 9335, 8772
VOICE = "Microsoft Zira Desktop"
PAD = 0.6  # seconds of calm after each line

# id, what is said, the screenshots shown (or a title card)
SCENES = [
    {"id": "title", "card": ("NEXA", "Agents recommend. Code enforces. Humans authorize."),
     "text": "Nexa Bank is an agentic fraud response platform. Agents investigate, plain code enforces the rules, and named humans authorize anything serious."},
    {"id": "app", "shots": ["01_app"],
     "text": "A customer pays from their own app. The bank, not the customer, decides whether the device is registered and whether the payee is new."},
    {"id": "grocery", "shots": ["02_paid"],
     "text": "An ordinary grocery payment goes through, and the monitor clears it. No case, and no model needed."},
    {"id": "takeover", "shots": ["03_takeover"],
     "text": "Now a takeover. A new phone, failed logins, and six quick transfers to new payees."},
    {"id": "feed", "shots": ["04_feed"],
     "text": "The monitor sees policy thresholds crossed, so cases open on their own, whatever any model thinks."},
    {"id": "case", "shots": ["05_case"],
     "text": "A model investigates. It chooses which records to look at, never sees a merchant name, and proposes findings."},
    {"id": "investigation", "shots": ["06_investigation"],
     "text": "Code then checks every claim against what the model actually looked at. It can add a finding, but never remove or invent one."},
    {"id": "recommendation", "shots": ["07_recommendation"],
     "text": "The recommendation is a freeze. That is level four, so two different roles must approve."},
    {"id": "approvals", "shots": ["08_one_seat", "09_completed"],
     "text": "The analyst approves, and nothing changes. Only when the risk officer approves too does the guarded tool freeze the account, once."},
    {"id": "frozen", "shots": ["10_frozen"],
     "text": "The customer's next payment is now refused. Every step sits in a tamper evident audit log."},
    {"id": "capability", "shots": ["11_capability"],
     "text": "To test it, we ran randomised honest and fraudulent traffic, with and without a model. Both catch the fraud, but only the model recognises structuring. No honest customer was restricted."},
    {"id": "close", "card": ("HONEST LIMITS", "Two seeds, synthetic data: evidence of behaviour, not proof on a real bank."),
     "text": "This is two seeds on synthetic data, not proof on a real bank. Agents recommend. Code enforces. Humans authorize."},
]


# --- talking to Chrome ---------------------------------------------------------------------------
class Page:
    """A tiny DevTools client."""

    def __init__(self, ws):  # type: ignore[no-untyped-def]
        self.ws, self.n = ws, 0

    async def call(self, method: str, **params):  # type: ignore[no-untyped-def]
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def js(self, expr: str):  # type: ignore[no-untyped-def]
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"])
        return r["result"].get("value")

    async def shot(self, name: str) -> None:
        data = (await self.call("Page.captureScreenshot", format="png"))["data"]
        SHOTS.mkdir(parents=True, exist_ok=True)
        (SHOTS / f"{name}.png").write_bytes(base64.b64decode(data))
        print(f"  shot {name}", flush=True)


def launch_chrome(extra: list[str], profile: str):  # type: ignore[no-untyped-def]
    args = [CHROME, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={OUT / profile}", *extra, "about:blank"]
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
            return proc, next(t for t in targets if t["type"] == "page")
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("Chrome did not start")


def get(path: str, token: str):  # type: ignore[no-untyped-def]
    req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}{path}", headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(req))


# --- 1. record the real run ----------------------------------------------------------------------
def start_server(providers: str):  # type: ignore[no-untyped-def]
    """Start the API with a model; its log goes to a file (a pipe nobody reads would fill and block it)."""
    cmd = [sys.executable, "-u", str(ROOT / "scripts" / "run_api.py"), "--demo", "--llm", "--providers", providers, "--port", str(API_PORT)]
    log_path = OUT / "server.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    deadline = time.time() + 90
    while time.time() < deadline:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        if "cannot use the LLM" in text:
            proc.terminate()
            raise SystemExit("cannot use the model: check the key in .env and --providers")
        if "Uvicorn running" in text:
            tokens = {m.group(2): m.group(3) for m in re.finditer(r"^\s+(\S+)\s+(\S+)\s+(\S{20,})\s*$", text, re.M)}
            return proc, tokens
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("server did not start")


async def record(providers: str) -> None:
    import websockets

    server, tokens = start_server(providers)
    chrome, page_info = launch_chrome(["--window-size=1600,900"], "profile-record")
    try:
        async with websockets.connect(page_info["webSocketDebuggerUrl"], max_size=2**26) as ws:
            p = Page(ws)
            await p.call("Page.enable")
            await p.call("Runtime.enable")
            await p.call("Emulation.setDeviceMetricsOverride", width=1600, height=900, deviceScaleFactor=1, mobile=False)
            await p.call("Page.navigate", url=f"http://127.0.0.1:{API_PORT}/")
            await asyncio.sleep(1.5)

            ready = {"customer": ".appform", "fraud_analyst": ".card.empty", "risk_officer": ".card.empty", "auditor": "#stage .card"}

            async def sign_in(role: str) -> None:
                await p.js(f"sessionStorage.setItem('nexa_token', {json.dumps(tokens[role])}); location.reload();")
                await asyncio.sleep(1.5)
                # the page finishes signing in by drawing its first screen: wait for it, or it can
                # overwrite what the script opens next (the server is slow while a model is working)
                for _ in range(60):
                    if await p.js(f"!!document.querySelector({json.dumps(ready[role])})"):
                        break
                    await asyncio.sleep(1)
                await asyncio.sleep(1.0)

            async def click(selector: str, text: str) -> None:
                await p.js(f"[...document.querySelectorAll({json.dumps(selector)})].find(b=>b.textContent.trim().toLowerCase()==={json.dumps(text.lower())}).click()")

            async def card_into_view(prefix: str) -> None:
                await p.js(f"[...document.querySelectorAll('.card > h2')].find(h=>h.textContent.trim().toLowerCase().startsWith({json.dumps(prefix.lower())})).scrollIntoView({{block:'start'}})")
                await asyncio.sleep(0.6)

            print("customer pays", flush=True)
            await sign_in("customer")
            await p.shot("01_app")
            await click("#stage button", "Everyday grocery")
            await click("#stage button", "Pay")
            await asyncio.sleep(2.0)
            await p.shot("02_paid")
            for _ in range(6):  # the page redraws its form after each payment, so fill it every time
                await click("#stage button", "Big transfer, new phone")
                await p.js("[...document.querySelectorAll('.fld')].find(l=>l.textContent.startsWith('Amount')).querySelector('input').value = 9000")
                await click("#stage button", "Pay")
                await asyncio.sleep(1.6)
            await p.shot("03_takeover")

            print("waiting for the freeze case (a model is investigating)", flush=True)
            analyst = tokens["fraud_analyst"]
            case_id = None
            deadline = time.time() + 480
            while time.time() < deadline and not case_id:
                pending = get("/approvals/pending", analyst)
                case_id = pending[0]["id"] if pending else None
                if not case_id:
                    await asyncio.sleep(5)
            if not case_id:
                raise SystemExit("no case reached approval: check the model and the log")
            while any(e["phase"] != "done" for e in get("/monitor/log", analyst)) and time.time() < deadline:
                await asyncio.sleep(4)

            await sign_in("fraud_analyst")
            await click("#tabs button", "Live feed")
            await asyncio.sleep(3.0)
            await p.shot("04_feed")
            await p.js(f"(async()=>{{await openTab('cases'); await show({json.dumps(case_id)});}})()")
            await asyncio.sleep(3.0)
            await p.shot("05_case")
            await card_into_view("Investigation")
            await p.shot("06_investigation")
            await card_into_view("Recommendation")
            await p.shot("07_recommendation")
            await click(".votes button", "approve")
            await asyncio.sleep(3.5)
            await card_into_view("Approval")
            await p.shot("08_one_seat")
            await sign_in("risk_officer")
            await p.js(f"(async()=>{{await openTab('cases'); await show({json.dumps(case_id)});}})()")
            await asyncio.sleep(2.5)
            if not await p.js("!!document.querySelector('.votes button')"):
                await p.shot("debug_no_vote_buttons")
                raise SystemExit("the risk officer sees no vote buttons: see shots/debug_no_vote_buttons.png")
            await click(".votes button", "approve")
            await asyncio.sleep(4.0)
            await p.shot("09_completed")

            await sign_in("customer")
            await click("#stage button", "Big transfer, new phone")
            await click("#stage button", "Pay")
            await asyncio.sleep(2.0)
            await p.shot("10_frozen")

            await sign_in("auditor")
            await click("#tabs button", "Capability")
            await asyncio.sleep(12.0)
            await card_into_view("5 ")
            await p.shot("11_capability")
            (OUT / "case_id.txt").write_text(case_id, encoding="utf-8")
    finally:
        chrome.terminate()
        server.terminate()


# --- 2. narrate with the built-in voice ------------------------------------------------------------
def narrate() -> None:
    AUDIO.mkdir(parents=True, exist_ok=True)
    jobs = [{"id": s["id"], "text": s["text"], "path": str(AUDIO / f"{s['id']}.wav")} for s in SCENES]
    (AUDIO / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    script = AUDIO / "speak.ps1"
    script.write_text(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        f"$s.SelectVoice('{VOICE}'); $s.Rate = -1\n"
        f"$jobs = Get-Content -Raw '{AUDIO / 'jobs.json'}' | ConvertFrom-Json\n"
        "foreach ($j in $jobs) { $s.SetOutputToWaveFile($j.path); $s.Speak($j.text); $s.SetOutputToNull() }\n",
        encoding="utf-8",
    )
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)
    for s in SCENES:
        with wave.open(str(AUDIO / f"{s['id']}.wav")) as w:
            print(f"  {s['id']:15} {w.getnframes() / w.getframerate():5.1f}s")


# --- 3. assemble the video inside Chrome --------------------------------------------------------------
PLAYER = """<!doctype html><meta charset="utf-8"><title>recording</title>
<body style="margin:0;background:#000"><canvas id="c" width="1600" height="1040"></canvas><script>
const W = 1600, H = 1040, SHOT_H = 900, c = document.getElementById("c"), x = c.getContext("2d");
const INK = "#17120f", PAPER = "#efe5cd", YEL = "#ffc928", ORG = "#ff5a1f", TEAL = "#00a39b", PINK = "#ff4fa3";
const load = u => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = u; });
function wrap(t, w) { const out = []; let line = ""; for (const word of t.split(" ")) { const next = line ? line + " " + word : word; if (x.measureText(next).width > w && line) { out.push(line); line = word; } else line = next; } if (line) out.push(line); return out; }
(async () => {
  const T = await (await fetch("timeline.json")).json();
  const ac = new AudioContext(), dest = ac.createMediaStreamDestination();
  await ac.resume();
  for (const s of T.scenes) {
    s.imgs = await Promise.all((s.shots || []).map(load));
    s.buf = await ac.decodeAudioData(await (await fetch(s.audio)).arrayBuffer());
  }
  const stream = c.captureStream(30); dest.stream.getAudioTracks().forEach(t => stream.addTrack(t));
  const rec = new MediaRecorder(stream, { mimeType: "video/webm;codecs=vp9,opus", videoBitsPerSecond: 2500000, audioBitsPerSecond: 96000 });
  const chunks = []; rec.ondataavailable = e => chunks.push(e.data);
  rec.onstop = async () => { await fetch("/upload", { method: "POST", body: new Blob(chunks, { type: "video/webm" }) }); document.title = "done"; };
  let at = 0; const starts = T.scenes.map(s => { const a = at; at += s.dur; return a; }); const total = at;
  const t0 = ac.currentTime + 1.0; T.scenes.forEach((s, i) => { const src = ac.createBufferSource(); src.buffer = s.buf; src.connect(dest); src.start(t0 + starts[i]); });
  rec.start(1000);
  function frame() {
    const t = ac.currentTime - t0;
    if (t >= total + 0.8) { rec.stop(); return; }
    const tt = Math.max(0, t), i = Math.max(0, starts.findLastIndex(a => a <= tt)), s = T.scenes[i], lt = tt - starts[i];
    x.fillStyle = PAPER; x.fillRect(0, 0, W, H);
    if (s.card) {
      x.fillStyle = ORG; x.fillRect(0, 0, W, 14); x.fillStyle = INK; x.textAlign = "center";
      x.font = "900 230px Bahnschrift, 'Arial Narrow', Impact, sans-serif"; x.fillText(s.card[0], W / 2, 420);
      x.fillStyle = TEAL; x.fillRect(W / 2 - 360, 460, 720, 10);
      x.fillStyle = INK; x.font = "800 46px Bahnschrift, 'Arial Narrow', sans-serif"; x.fillText(s.card[1], W / 2, 560);
    } else {
      const n = s.imgs.length, k = Math.min(n - 1, Math.floor(lt / (s.dur / n)));
      x.drawImage(s.imgs[k], 0, 0, W, SHOT_H);
      x.strokeStyle = INK; x.lineWidth = 6; x.strokeRect(0, 0, W, SHOT_H);
    }
    x.fillStyle = INK; x.fillRect(0, SHOT_H, W, H - SHOT_H);
    x.fillStyle = YEL; x.font = "800 31px Bahnschrift, 'Arial Narrow', sans-serif"; x.textAlign = "center";
    wrap(s.text, W - 200).slice(0, 3).forEach((l, j) => x.fillText(l, W / 2, SHOT_H + 46 + j * 40));
    x.fillStyle = ORG; x.fillRect(0, H - 10, W * Math.min(1, tt / total), 10);
    requestAnimationFrame(frame);
  }
  frame();
})();
</script>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the assets and receives the finished video."""

    out_file: Path = OUT / "nexa-agentic-demo.webm"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.out_file.write_bytes(self.rfile.read(length))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args) -> None:  # type: ignore[no-untyped-def]
        pass


async def assemble() -> None:
    import websockets

    scenes = []
    for s in SCENES:
        with wave.open(str(AUDIO / f"{s['id']}.wav")) as w:
            seconds = w.getnframes() / w.getframerate()
        scenes.append({
            "text": s["text"], "card": s.get("card"), "audio": f"audio/{s['id']}.wav",
            "shots": [f"shots/{n}.png" for n in s.get("shots", [])], "dur": round(seconds + PAD, 2),
        })
        for n in s.get("shots", []):
            if not (SHOTS / f"{n}.png").exists():
                raise SystemExit(f"missing screenshot {n}: run 'record' first")
    total = sum(s["dur"] for s in scenes)
    print(f"video length about {total + 1.8:.0f}s", flush=True)
    (OUT / "timeline.json").write_text(json.dumps({"scenes": scenes}), encoding="utf-8")
    (OUT / "player.html").write_text(PLAYER, encoding="utf-8")
    Handler.out_file.unlink(missing_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", FILE_PORT), partial(Handler, directory=str(OUT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    chrome, page_info = launch_chrome(["--autoplay-policy=no-user-gesture-required", "--window-size=1600,1040"], "profile-assemble")
    try:
        async with websockets.connect(page_info["webSocketDebuggerUrl"], max_size=2**26) as ws:
            p = Page(ws)
            await p.call("Page.enable")
            await p.call("Runtime.enable")
            await p.call("Page.navigate", url=f"http://127.0.0.1:{FILE_PORT}/player.html")
            deadline = time.time() + total + 90
            while time.time() < deadline:
                await asyncio.sleep(3)
                if await p.js("document.title") == "done":
                    break
            else:
                raise SystemExit("the recording did not finish")
    finally:
        chrome.terminate()
        server.shutdown()
    size = Handler.out_file.stat().st_size / 1e6
    print(f"wrote {Handler.out_file} ({size:.1f} MB)")


def main() -> int:
    """Run one stage or all of them."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stage", choices=["record", "narrate", "assemble", "all"])
    parser.add_argument("--providers", default="anthropic,gemini", help="model order for the recorded run")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.stage in ("record", "all"):
        asyncio.run(record(args.providers))
    if args.stage in ("narrate", "all"):
        narrate()
    if args.stage in ("assemble", "all"):
        asyncio.run(assemble())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
