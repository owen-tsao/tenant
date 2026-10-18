"""Prepare an original local demo clip; no subscription or downloaded music."""
from pathlib import Path
import array
import hashlib
import math
import subprocess
import sys
import wave

root = Path(__file__).resolve().parent.parent
clip = root / ".venv" / "tenant-audio" / "tenant-calm.wav"
clip.parent.mkdir(parents=True, exist_ok=True)
rate, seconds = 16000, 90
if not clip.exists():
    samples = array.array("h")
    chords = [(130.81, 164.81, 196.00), (110.00, 130.81, 164.81),
              (87.31, 110.00, 130.81), (98.00, 123.47, 146.83)]
    for n in range(rate * seconds):
        t = n / rate
        chord = chords[int(t // 6) % len(chords)]
        envelope = min(1, t / 2, (seconds - t) / 2) * (.65 + .35 * math.sin(math.pi * (t % 6) / 6))
        value = sum(math.sin(2 * math.pi * f * t) for f in chord) / len(chord)
        samples.append(round(32767 * .16 * envelope * value))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(clip), "wb") as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        out.writeframes(samples.tobytes())

script = '''on run argv
set playlistName to item 1 of argv
set assetPath to item 2 of argv
tell application "Music"
if not (exists playlist playlistName) then make new user playlist with properties {name:playlistName}
set p to playlist playlistName
set ts to file tracks of p
if (count of ts) > 0 then
set localFile to location of item 1 of ts
else
add (POSIX file assetPath) to p
return "Local demo playlist prepared."
end if
end tell
return "EXISTING:" & (POSIX path of localFile)
end run'''
result = subprocess.run(["/usr/bin/osascript", "-e", script, "Tenant", str(clip)],
                        capture_output=True, text=True, timeout=20)
if result.returncode:
    print("Music setup failed; existing playlist contents were not overwritten.")
    print(result.stderr[:500])
    raise SystemExit(1)
message = result.stdout.strip()
if message.startswith('EXISTING:'):
    existing = Path(message.removeprefix('EXISTING:'))
    if not existing.is_file() or hashlib.sha256(existing.read_bytes()).digest() != hashlib.sha256(clip.read_bytes()).digest():
        raise SystemExit('Prepared playlist already contains different media; left unchanged.')
    print('Existing demo playlist retained.')
else:
    print(message)
