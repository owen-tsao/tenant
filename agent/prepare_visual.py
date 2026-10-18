"""Prepare one silent ambient video for the existing checksum-bound song player.

Uses installed FFmpeg, numpy and Pillow. No player, audio output, network,
browser, microphone or live configuration is opened or changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import wave

import numpy as np
from PIL import Image

from agent.song_audio import load_recording

FPS, WIDTH, HEIGHT, TILE, BANDS = 60, 1280, 720, 600, 64
_Y, _X = np.mgrid[-1:1:320j, -1:1:320j].astype(np.float32)
_R = np.sqrt(_X * _X + _Y * _Y)
_ANGLE = np.arctan2(_Y, _X)
_PHASE = (_ANGLE + np.pi) * (BANDS / (2 * np.pi))
_INDEX = np.floor(_PHASE).astype(int) % BANDS
_FRACTION = _PHASE - np.floor(_PHASE)


def spectrum(recording):
    with wave.open(recording['audio_path'], 'rb') as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError('This prepared visual expects the existing mono PCM16 asset.')
        rate = audio.getframerate()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), '<i2').astype(np.float32) / 32768
    count = math.ceil(recording['duration_seconds'] * FPS)
    window = np.hanning(2048)
    padded = np.pad(samples, (1024, 2048))
    bins = np.fft.rfftfreq(2048, 1 / rate)
    edges = np.geomspace(45, min(10000, rate / 2), BANDS + 1)
    ranges = [(max(1, np.searchsorted(bins, a)), max(2, np.searchsorted(bins, b)))
              for a, b in zip(edges, edges[1:])]
    values = np.empty((count, BANDS), np.float32)
    for frame in range(count):
        start = round(frame * rate / FPS)
        energy = np.abs(np.fft.rfft(padded[start:start + 2048] * window))
        values[frame] = [np.mean(energy[a:max(a + 1, b)]) for a, b in ranges]
    ceiling = np.maximum(np.percentile(values, 95, axis=0), .01)
    values = np.clip(values / ceiling, 0, 1) ** .65
    for frame in range(1, count):
        values[frame] = values[frame - 1] * .68 + values[frame] * .32
    return values


def draw_frame(t, levels, beats):
    """Iridescent translucent membranes, deformed by the actual audio bands."""
    nearest = np.searchsorted(beats, t)
    pulse = max((math.exp(-((t - beats[i]) / .09) ** 2)
                 for i in (nearest - 1, nearest) if 0 <= i < len(beats)), default=0)
    levels = (levels * .4 + np.roll(levels, 1) * .2 + np.roll(levels, -1) * .2
              + np.roll(levels, 2) * .1 + np.roll(levels, -2) * .1)
    energy = levels[_INDEX] * (1 - _FRACTION) + levels[(_INDEX + 1) % BANDS] * _FRACTION
    rgb = np.zeros((*_R.shape, 3), np.float32)
    cyan = np.array([.035, .62, 1.], dtype=np.float32)
    pink = np.array([.88, .055, .68], dtype=np.float32)
    for sheet in range(3):
        phase = sheet * 2.07
        radius = (.665 + .027 * pulse + .025 * (energy - .5)
                  + .046 * np.sin((sheet + 2) * _ANGLE + t * (.29 - sheet * .24) + phase)
                  + .019 * np.cos(2 * _ANGLE - t * .37 + phase))
        width = .031 + .019 * (.5 + .5 * np.sin(2 * _ANGLE + phase - t * .41)) + .009 * energy
        distance = _R - radius
        body = np.exp(-(distance / width) ** 2)
        fold = .5 + .5 * np.sin(distance / width * 3.3 + _ANGLE * 2 - t * .31 + phase)
        filament = np.exp(-((distance - width * .38) / .0065) ** 2)
        inner = np.exp(-((distance + width * .55) / .011) ** 2)
        spot = np.maximum(0, np.cos(_ANGLE * 2 - t * .26 + phase)) ** 8
        brightness = body * (.065 + .14 * fold) + filament * (.12 + .42 * spot) + inner * .075
        hue = (.5 + .5 * np.sin(_ANGLE + phase + t * .16))[..., None]
        color = cyan * (1 - hue) + pink * hue
        rgb += color * brightness[..., None]
        rgb += (filament * spot * .28)[..., None]
        rgb += color * (.028 * np.exp(-(distance / (width * 2.3)) ** 2))[..., None]
    rgb = (1 - np.exp(-rgb * 2.7)).astype(np.float32)
    alpha = np.max(rgb, axis=2)
    rgba = np.empty((*_R.shape, 4), np.uint8)
    rgba[..., :3] = np.clip(rgb / np.maximum(alpha[..., None], 1e-7) * 255, 0, 255).astype(np.uint8)
    rgba[..., 3] = (alpha * 255).astype(np.uint8)
    return Image.fromarray(rgba).resize((TILE, TILE), Image.Resampling.BICUBIC)


def prepare(manifest):
    recording = load_recording(manifest)
    target = manifest.parent / 'ambient-fluid-orb.mp4'
    temporary = manifest.parent / 'ambient-fluid-orb.pending.mp4'
    values, beats = spectrum(recording), np.asarray(recording['beat_seconds'])
    preview = draw_frame(float(beats[0]), values[round(beats[0] * FPS)], beats)
    preview.save(manifest.parent / 'ambient-fluid-preview.png')
    command = [shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y',
        '-f', 'lavfi', '-i',
        f'gradients=s={WIDTH}x{HEIGHT}:r={FPS}:c0=0x02030b:c1=0x0d061b:c2=0x03121b:n=3:seed=73:speed=0.009:type=spiral',
        '-f', 'rawvideo', '-pixel_format', 'rgba', '-video_size', f'{TILE}x{TILE}',
        '-framerate', str(FPS), '-i', 'pipe:0', '-filter_complex',
        '[0:v][1:v]overlay=(W-w)/2:(H-h)/2:shortest=1,format=yuv420p[v]',
        '-map', '[v]', '-an', '-t', str(recording['duration_seconds']),
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-threads', '4',
        '-movflags', '+faststart', str(temporary)]
    log = manifest.parent / 'ambient-render.log'
    with log.open('wb') as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            for i, levels in enumerate(values):
                process.stdin.write(draw_frame(i / FPS, levels, beats).tobytes())
            process.stdin.close()
            if process.wait(timeout=45):
                raise RuntimeError('FFmpeg rendering failed; inspect the local render log.')
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            temporary.unlink(missing_ok=True)
            raise
    result = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-show_streams',
                             '-show_format', '-of', 'json', str(temporary)],
                            capture_output=True, text=True, check=True, timeout=10)
    probe = json.loads(result.stdout)
    if [s['codec_type'] for s in probe['streams']] != ['video']:
        raise ValueError('The visual asset must be silent video only.')
    duration = float(probe['format']['duration'])
    if abs(duration - recording['duration_seconds']) > 1 / FPS + .01:
        raise ValueError('The rendered visual duration does not match the recording.')
    temporary.replace(target)
    proposed = json.loads(manifest.read_text())
    proposed['visual'] = dict(path=str(target.resolve()), sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        source_sha256=recording['sha256'], width=WIDTH, height=HEIGHT, fps=FPS,
        duration_seconds=duration,
        description='Fluid iridescent energy orb, deformed by CYANIDE audio and analyzed beats, at60fps. Same player clock; external TV window, no fullscreen.')
    output = manifest.parent / 'song-with-fluid-visual.json'
    output.write_text(json.dumps(proposed, indent=2) + '\n')
    output.chmod(0o600)
    print(json.dumps({'prepared': True, 'frames': len(values), 'duration_seconds': duration,
                      'silent_video': True, 'proposed_manifest': str(output),
                      'live_manifest_changed': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    prepare(parser.parse_args().manifest.resolve())
