"""Browser mic-to-ear harness: the exact call path, minus Meta.

Serves a page whose getUserMedia SDP offer enters the same RTCBridge + Gemini
Live + tool pipeline a WhatsApp call uses (with a fake signaling API). Talk in
Sinhala/Tamil/English and hear Sarasavi answer, tools included.

  uv run python devtools/voice_browser.py     # then open http://localhost:8765

Needs GOOGLE_API_KEY in .env. Dev-only: never expose this port publicly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

SESSION_PHONE = "browser-tester"

PAGE = """<!doctype html>
<meta charset="utf-8"><title>Sarasavi voice loopback</title>
<body style="font-family:sans-serif;max-width:40em;margin:3em auto">
<h2>Sarasavi Power — mic loopback</h2>
<button id="start">Start call</button> <button id="stop" disabled>Hang up</button>
<p id="status">idle</p>
<audio id="remote" autoplay></audio>
<script>
let pc;
const status = (t) => document.getElementById("status").textContent = t;
document.getElementById("start").onclick = async () => {
  pc = new RTCPeerConnection();
  pc.ontrack = (e) => { document.getElementById("remote").srcObject = e.streams[0]; };
  const mic = await navigator.mediaDevices.getUserMedia({audio: true});
  mic.getTracks().forEach(t => pc.addTrack(t, mic));
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise(r => { if (pc.iceGatheringState === "complete") r();
    pc.onicegatheringstatechange = () => pc.iceGatheringState === "complete" && r(); });
  status("connecting...");
  const resp = await fetch("/dev/offer", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({sdp: pc.localDescription.sdp})});
  const answer = await resp.json();
  await pc.setRemoteDescription({type: "answer", sdp: answer.sdp});
  pc.onconnectionstatechange = () => status(pc.connectionState);
  document.getElementById("stop").disabled = false;
};
document.getElementById("stop").onclick = () => { pc && pc.close(); status("closed"); };
</script>
"""


class FakeCallsAPI:
    """Signaling is the browser's fetch round-trip; every Graph call is a no-op."""

    async def pre_accept(self, call_id, sdp):
        return True

    async def accept(self, call_id, sdp):
        return True

    async def reject(self, call_id):
        return True

    async def terminate(self, call_id):
        return True


def build_app() -> FastAPI:
    # Register agents so Runtime has a session store for the tool executor.
    from agentkernel.adk import GoogleADKModule

    from agent import AGENTS
    from voice.bridge import RTCBridge
    from voice.call_manager import CallSession
    from voice.live_agent import LIVE_MODEL, VoiceToolExecutor, build_live_config

    GoogleADKModule(AGENTS)
    app = FastAPI()

    @app.get("/")
    async def page() -> HTMLResponse:
        return HTMLResponse(PAGE)

    @app.post("/dev/offer")
    async def offer(body: dict) -> dict:
        import asyncio

        from google import genai

        bridge = RTCBridge()
        answer_sdp = await bridge.answer(body["sdp"])

        def live_connect():
            return genai.Client().aio.live.connect(model=LIVE_MODEL, config=build_live_config())

        session = CallSession(
            "browser-call",
            SESSION_PHONE,
            body["sdp"],
            calls_api=FakeCallsAPI(),
            bridge=bridge,
            live_connect=live_connect,
            executor=VoiceToolExecutor(SESSION_PHONE),
        )

        async def run_active_phase():
            # The bridge already answered; skip run()'s signaling half by driving
            # the active phase directly through the same code path.
            if await bridge.wait_connected(20):
                session.state = session.state.__class__.ACTIVE
                async with live_connect() as live:
                    await session._greet(live)
                    pumps = [
                        asyncio.create_task(bridge.pump_caller_to_gemini(live)),
                        asyncio.create_task(
                            bridge.pump_gemini_to_caller(live, session.transcript, session._make_tool_handler(live))
                        ),
                        asyncio.create_task(bridge.wait_disconnected()),
                    ]
                    session._tasks = pumps
                    await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
            await session.close("browser hangup")
            print("\n--- transcript ---")
            for line in session.transcript:
                print(line)

        asyncio.create_task(run_active_phase())
        return {"sdp": answer_sdp}

    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=8765)
