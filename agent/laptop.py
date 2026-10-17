"""Tenant room audio. OS effects are synchronous and invoked only via to_thread."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class AudioError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Config:
    playlist: str | None = None
    app_path: str = "/System/Applications/Music.app"


# Values are passed as argv, never interpolated into executable AppleScript.
MUSIC_PROBE = '''on run argv
tell application "Music"
set p to playlist (item 1 of argv)
set ts to file tracks of p
if (count of ts) is 0 then return 0
set localFile to location of item 1 of ts
if localFile is missing value then error "Track is not downloaded."
end tell
get info for localFile
return 1
end run'''
MUSIC_PLAY = '''on run argv
tell application "Music"
set p to playlist (item 1 of argv)
set ts to file tracks of p
if (count of ts) is 0 then error "No local tracks; import a local audio file into the configured playlist."
set t to item 1 of ts
set localFile to location of t
if localFile is missing value then error "Track is not downloaded; import a local audio file."
end tell
get info for localFile
tell application "Music"
play t
repeat 20 times
if player state is playing then return player state as text
delay 0.1
end repeat
return player state as text
end tell
end run'''
MUSIC_PAUSE = '''tell application "Music"
pause
repeat 20 times
if player state is paused or player state is stopped then return player state as text
delay 0.1
end repeat
return player state as text
end tell'''
VOLUME = '''on run argv
set volume output volume (item 1 of argv as integer)
return output volume of (get volume settings)
end run'''


class AudioDispatcher:
    """Inject runner/system/exists for deterministic tests; no effects on import."""
    def __init__(self, config: Config | None = None, *, runner=subprocess.run,
                 system=platform.system, exists=lambda p: Path(p).exists()):
        self.config = config or Config()
        self.runner, self.exists = runner, exists
        self.is_mac = (system() if callable(system) else system) == "Darwin"
        self.music_ready = False
        self.discovery_error = "Set TENANT_MUSIC_PLAYLIST to a playlist containing downloaded local audio."

    def _run(self, argv, timeout, *, input=None):
        try:
            out = self.runner(argv, input=input, capture_output=True, text=True,
                              timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise AudioError("UNKNOWN", "OS command timed out; outcome unknown. Do not retry automatically.") from exc
        except OSError as exc:
            raise AudioError("UNSUPPORTED", "Required macOS command is unavailable.") from exc
        if out.returncode:
            # Do not echo arbitrary OS output, user text, paths, or environment.
            if "-1743" in (out.stderr or ""):
                raise AudioError("PERMISSION", "Allow Terminal/Python to control Music in macOS Privacy & Security > Automation.")
            raise AudioError("UNKNOWN", "macOS did not confirm the audio command; it may have acted. Do not retry automatically.")
        return out.stdout.strip()

    def _script(self, script, *args, timeout):
        return self._run(["/usr/bin/osascript", "-e", script, *args], timeout)

    def discover(self, timeout=4.0):
        """Read-only Music probe; may trigger macOS's Automation permission prompt."""
        self.music_ready = False
        if self.is_mac and self.config.playlist and self.exists(self.config.app_path) and self.exists("/usr/bin/osascript"):
            try:
                count = self._script(MUSIC_PROBE, self.config.playlist, timeout=timeout)
                self.music_ready = int(count) > 0
                if not self.music_ready:
                    self.discovery_error = "Configured Music playlist has no local file tracks; import downloaded audio."
            except (AudioError, ValueError) as exc:
                self.discovery_error = str(exc)
        return self.capabilities()

    def capabilities(self):
        caps = {}
        if not self.is_mac:
            return caps
        if self.exists("/usr/bin/osascript"):
            caps["volume"] = {"description": "Set Mac output volume from 0 to 100; output hardware may have fixed volume.", "args": {"level": {"type": "integer", "minimum": 0, "maximum": 100}}}
        if self.exists("/usr/bin/say") and self.exists("/usr/bin/afplay"):
            caps["say"] = {"description": "Speak a short phrase through the Mac's current audio output.", "args": {"text": {"type": "string", "maxLength": 160}}}
        if self.music_ready:
            caps["music.play"] = {"description": "Play the first downloaded local track in the prepared room playlist; no streaming or arbitrary search.", "args": {}}
            caps["music.pause"] = {"description": "Pause Music on this Mac.", "args": {}}
        return caps

    def dispatch(self, cap, args, timeout=4.0):
        if not isinstance(args, dict):
            raise AudioError("FAILED", "args must be an object.")
        if cap not in self.capabilities():
            raise AudioError("UNSUPPORTED", self.discovery_error if cap in ("music.play", "music.pause") else "Capability is not available on this device.")
        if cap == "volume":
            level = args.get("level")
            if set(args) != {"level"} or type(level) is not int or not 0 <= level <= 100:
                raise AudioError("FAILED", "volume requires integer level from 0 to 100.")
            observed = self._script(VOLUME, str(level), timeout=timeout)
            if observed != str(level):
                raise AudioError("FAILED", "Output volume did not match; this audio output may have fixed volume.")
            return {"level": level, "audible_verified": False}
        if cap == "say":
            text = args.get("text")
            if set(args) != {"text"} or not isinstance(text, str) or not text.strip() or len(text) > 160 or "\x00" in text:
                raise AudioError("FAILED", "say requires 1–160 characters of nonempty text without NUL.")
            # Render first, then use the normal default audio output. Direct say
            # playback returned success but was inaudible on the actual room Mac.
            # One playback only: never retry an uncertain physical effect.
            expires_at = time.monotonic() + timeout
            with tempfile.TemporaryDirectory(prefix="tenant-speech-") as directory:
                audio = str(Path(directory) / 'speech.aiff')
                self._run(["/usr/bin/say", "-o", audio], timeout, input=text)
                remaining = expires_at - time.monotonic()
                if remaining <= 0:
                    raise AudioError("FAILED", "Deadline elapsed before speech playback; no audio started.")
                self._run(["/usr/bin/afplay", audio], remaining)
            return {"spoken": True, "audible_verified": False}
        if args:
            raise AudioError("FAILED", "This prepared music capability accepts no arguments.")
        state = self._script(MUSIC_PLAY, self.config.playlist, timeout=timeout) if cap == "music.play" else self._script(MUSIC_PAUSE, timeout=timeout)
        expected = {"playing"} if cap == "music.play" else {"paused", "stopped"}
        if state.lower() not in expected:
            raise AudioError("UNKNOWN", "Music did not confirm the requested state; it may have acted. Do not retry automatically.")
        return {"state": state.lower(), "audible_verified": False}


class DeviceAgent:
    def __init__(self, dispatcher, room, device_id="laptop", label="Room speaker", *, ledger_limit=4096):
        self.dispatcher, self.room = dispatcher, room
        self.device_id, self.label = device_id, label
        self.epoch = -1
        self.ledger = {}
        self.ledger_limit = ledger_limit
        self.busy = False

    def hello(self):
        return {"type": "hello", "id": self.device_id, "label": self.label,
                "room": self.room, "caps": self.dispatcher.capabilities()}

    @staticmethod
    def error(req, code, message):
        return {"type": "err", "req": req, "code": code, "message": message}

    async def handle(self, frame, *, received_at=None):
        received_at = time.monotonic() if received_at is None else received_at
        if not isinstance(frame, dict):
            return None
        if frame.get("type") == "ping":
            return {"type": "pong"}
        if frame.get("type") == "welcome":
            room = frame.get("room")
            if isinstance(room, str) and 1 <= len(room) <= 32 and room.isalnum():
                self.room = room
            return None
        if frame.get("type") != "do":
            return None
        req = frame.get("req")
        if not isinstance(req, str) or not req or len(req) > 128:
            return self.error(req if isinstance(req, str) else None, "FAILED", "Invalid req.")
        epoch = frame.get("epoch")
        if type(epoch) is not int or epoch < 0:
            return self.error(req, "FAILED", "Missing or invalid epoch.")
        if epoch < self.epoch:
            return self.error(req, "STALE", "Older room epoch.")
        self.epoch = epoch
        if req in self.ledger:
            return self.ledger[req]
        if len(self.ledger) >= self.ledger_limit:
            return self.error(req, "BUSY", "Request ledger full; host must restart agent. No actions replayed.")
        if self.busy:
            result = self.error(req, "BUSY", "Another audio action is in progress.")
            self.ledger[req] = result
            return result
        deadline = frame.get("deadline_ms", 5000)
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0:
            return self.error(req, "FAILED", "Invalid deadline_ms.")
        self.ledger[req] = self.error(req, "FAILED", "Action started; outcome unknown. Not replayed.")
        self.busy = True
        expires_at = received_at + deadline / 1000

        def execute_before_deadline():
            # Executor congestion counts against the request budget too. A queued
            # worker must never initiate a physical action after its expiry.
            remaining = expires_at - time.monotonic()
            if remaining <= 0:
                raise AudioError("FAILED", "Deadline elapsed before execution; no action started.")
            return self.dispatcher.dispatch(frame.get("cap"), frame.get("args", {}), min(remaining, 4.0))

        try:
            result = await asyncio.to_thread(execute_before_deadline)
            response = {"type": "ok", "req": req, "result": result}
        except AudioError as exc:
            response = self.error(req, exc.code, exc.message)
        except Exception:
            response = self.error(req, "UNKNOWN", "Unexpected audio failure; outcome unknown. Not replayed.")
        finally:
            self.busy = False
        self.ledger[req] = response
        return response

    async def session(self, ws):
        await ws.send(json.dumps(self.hello()))
        tasks = set()

        async def execute(frame, received_at):
            response = await self.handle(frame, received_at=received_at)
            if response is not None:
                await ws.send(json.dumps(response))

        try:
            async for raw in ws:
                received_at = time.monotonic()
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(frame, dict):
                    continue
                if frame.get("type") == "do":
                    task = asyncio.create_task(execute(frame, received_at))
                    tasks.add(task)
                    # Keep tasks until disconnect so all exceptions are retrieved.
                    if len(tasks) > 64:
                        finished = {t for t in tasks if t.done()}
                        for t in finished:
                            t.exception()
                        tasks -= finished
                else:
                    await execute(frame, received_at)
        finally:
            # Do not cancel to_thread: cancellation cannot stop the OS action.
            # Finish recording outcome before reconnect; never send on a new socket.
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self, url, connect=None):
        if connect is None:
            from websockets.asyncio.client import connect
        delay = 0.5
        while True:
            try:
                async with connect(url, open_timeout=5, close_timeout=1, max_size=65536, ping_interval=5, ping_timeout=10) as ws:
                    delay = 0.5
                    await self.session(ws)
            except asyncio.CancelledError:
                raise
            except Exception:
                # URLs contain device secrets. Never print exception/URL.
                print("Audio connection unavailable; reconnecting without replay.", flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 4.0)


def device_url(base, token):
    parts = urlsplit(base)
    if parts.scheme not in ("ws", "wss") or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("TENANT_WS_URL must be a ws/wss URL without credentials or fragment.")
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "t"]
    query.append(("t", token))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


async def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Probe local capabilities without connecting or playing audio")
    options = parser.parse_args()
    dispatcher = AudioDispatcher(Config(playlist=os.environ.get("TENANT_MUSIC_PLAYLIST")))
    caps = await asyncio.to_thread(dispatcher.discover)
    print(json.dumps({"caps": caps, "music_note": dispatcher.discovery_error if not dispatcher.music_ready else "Prepared local playlist ready; audibility unverified."}))
    if options.check:
        return
    if not caps:
        raise SystemExit("No macOS audio capabilities available; run on the room Mac.")
    room, token = os.environ.get("ROOM_CODE"), os.environ.get("DEVICE_TOKEN")
    if not room or not token:
        raise SystemExit("Set ROOM_CODE and DEVICE_TOKEN in this process environment.")
    url = device_url(os.environ.get("TENANT_WS_URL", "ws://127.0.0.1:8000/ws/device"), token)
    await DeviceAgent(dispatcher, room, os.environ.get("TENANT_DEVICE_ID", "laptop"), os.environ.get("TENANT_DEVICE_LABEL", "Room speaker")).run(url)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
