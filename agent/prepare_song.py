"""Prepare one explicitly selected public recording; never play or change audio.

Uses existing yt-dlp/FFmpeg plus optional librosa. Stream URLs stay in memory;
only a private canonical PCM cache and checksum-bound beat map are retained.
No account, browser cookies, catalog search, purchase or generated substitute.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import wave


SOURCE = 'https://www.youtube.com/watch?v=Jnm3ukzmJe4'
SOURCE_ID = 'Jnm3ukzmJe4'


def prepare(directory, *, source=SOURCE):
    if source != SOURCE:
        raise ValueError('Only the selected official Daniel Caesar CYANIDE source is configured.')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    result = subprocess.run([shutil.which('yt-dlp') or 'yt-dlp', '--ignore-config',
        '--skip-download', '--dump-single-json', '--no-playlist', '--no-warnings',
        '--socket-timeout', '10', '--retries', '0', '--extractor-retries', '0',
        '--format', 'bestaudio', source], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise ValueError('Selected public recording could not be resolved; no account fallback or retry.')
    info = json.loads(result.stdout)
    if (info.get('id') != SOURCE_ID or info.get('artist') != 'Daniel Caesar'
            or info.get('title') != 'CYANIDE' or info.get('is_live') or not info.get('url', '').startswith('https://')):
        raise ValueError('The selected recording identity was not confirmed.')
    path = directory / 'cyanide.wav'
    # Decode the selected stream once. Analysis and playback use these exact
    # bytes, eliminating independent decoder/encoder-delay timeline differences.
    decoded = subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-nostdin', '-v', 'error',
        '-i', info['url'], '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '22050',
        '-c:a', 'pcm_s16le', '-y', str(path)], capture_output=True, timeout=120)
    if decoded.returncode:
        path.unlink(missing_ok=True)
        raise ValueError('The selected audio stream could not be decoded; no playback occurred.')
    os.chmod(path, 0o600)
    import librosa
    import numpy as np
    with wave.open(str(path), 'rb') as clip:
        rate, frames = clip.getframerate(), clip.getnframes()
        audio = np.frombuffer(clip.readframes(frames), dtype='<i2').astype(np.float32) / 32768
    tempo, beats = librosa.beat.beat_track(y=audio, sr=rate, hop_length=256, units='time', trim=True)
    times = [float(value) for value in beats]
    if len(times) < 3:
        raise ValueError('No usable recording-derived beat timeline was found; no guessed BPM fallback.')
    identity = hashlib.sha256(path.read_bytes()).hexdigest()
    record = {'version': 1, 'song_id': 'daniel-caesar-cyanide-' + identity[:12],
        'title': 'CYANIDE', 'artist': 'Daniel Caesar', 'source_url': source,
        'source_id': SOURCE_ID, 'source_format_id': info.get('format_id'),
        'audio_path': str(path), 'sha256': identity, 'duration_seconds': frames / rate,
        'beat_seconds': times, 'estimated_bpm': float(np.asarray(tempo).reshape(-1)[0]),
        'analysis': {'tool': 'librosa', 'version': librosa.__version__,
                     'method': 'beat_track', 'sample_rate': rate, 'hop_length': 256,
                     'timeline': 'zero is first PCM sample; same exact WAV is played',
                     'physical_alignment_verified': False}}
    manifest = directory / 'song.json'
    temporary = directory / 'song.json.pending'
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(manifest)
    return record, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    try:
        record, manifest = prepare(args.directory)
    except Exception:
        # Extractor/decoder errors can include expiring signed media URLs.
        print(json.dumps({'ok': False, 'message': 'Selected-source preparation failed; inspect prerequisites without dumping stream URLs. No playback or automatic retry.'}))
        return 1
    print(json.dumps({'ok': True, 'song_id': record['song_id'], 'artist': record['artist'],
        'title': record['title'], 'duration_seconds': record['duration_seconds'],
        'detected_beats': len(record['beat_seconds']), 'estimated_bpm': record['estimated_bpm'],
        'sha256': record['sha256'], 'manifest': str(manifest), 'played': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
