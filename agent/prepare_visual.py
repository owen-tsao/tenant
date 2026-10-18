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
from PIL import Image, ImageDraw, ImageFont

from agent.song_audio import load_recording

FPS, WIDTH, HEIGHT, TILE, BANDS = 30, 1280, 720, 600, 64


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
        values[frame] = np.maximum(values[frame], values[frame - 1] * .84)
    return values


def fonts():
    path = '/System/Library/Fonts/Supplemental/Arial.ttf'
    if Path(path).is_file():
        return ImageFont.truetype(path, 30), ImageFont.truetype(path, 17)
    return ImageFont.load_default(size=30), ImageFont.load_default(size=17)


def draw_frame(t, levels, beats, font):
    image = Image.new('RGBA', (TILE, TILE))
    draw = ImageDraw.Draw(image)
    previous = np.searchsorted(beats, t, side='right') - 1
    elapsed = t - beats[previous] if previous >= 0 else 100
    pulse = math.exp(-elapsed / .13) if elapsed >= 0 else 0
    radius, center = 174 + pulse * 9, TILE / 2
    for extra, alpha, width in ((14, 12, 23), (7, 22, 12), (0, 235, 3)):
        r = radius + extra
        draw.ellipse((center - r, center - r, center + r, center + r),
                     outline=(159, 237, 232, alpha), width=width)
    for i, value in enumerate(levels):
        angle = i * 2 * math.pi / BANDS - math.pi / 2
        length = 4 + value * 48 + pulse * 6
        inner, outer = radius + 11, radius + 11 + length
        color = (int(159 + 58 * i / BANDS), int(232 - 60 * i / BANDS), 230, 210)
        draw.line((center + inner * math.cos(angle), center + inner * math.sin(angle),
                   center + outer * math.cos(angle), center + outer * math.sin(angle)), fill=color, width=3)
    draw.text((center, center - 12), 'CYANIDE', font=font[0], fill=(245, 238, 247, 240), anchor='mm')
    draw.text((center, center + 29), 'DANIEL CAESAR', font=font[1], fill=(198, 197, 218, 220), anchor='mm')
    return image


def prepare(manifest):
    recording = load_recording(manifest)
    target = manifest.parent / 'ambient-beat-ring.mp4'
    temporary = manifest.parent / 'ambient-beat-ring.pending.mp4'
    values, beats, font = spectrum(recording), np.asarray(recording['beat_seconds']), fonts()
    preview = draw_frame(float(beats[0]), values[round(beats[0] * FPS)], beats, font)
    preview.save(manifest.parent / 'ambient-ring-preview.png')
    command = [shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y',
        '-f', 'lavfi', '-i',
        f'gradients=s={WIDTH}x{HEIGHT}:r={FPS}:c0=0x100d1c:c1=0x254448:c2=0x48304e:n=3:seed=73:speed=0.006:type=spiral',
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
                process.stdin.write(draw_frame(i / FPS, levels, beats, font).tobytes())
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
        description='Mellow ambient video with circular audio spectrum and analyzed CYANIDE beat pulses. Same player clock; external TV window, no fullscreen.')
    output = manifest.parent / 'song-with-visual.json'
    output.write_text(json.dumps(proposed, indent=2) + '\n')
    output.chmod(0o600)
    print(json.dumps({'prepared': True, 'frames': len(values), 'duration_seconds': duration,
                      'silent_video': True, 'proposed_manifest': str(output),
                      'live_manifest_changed': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    prepare(parser.parse_args().manifest.resolve())
