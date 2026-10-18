"""Recording-derived beats mapped from a bracketed live player observation.

The request/receipt bracket belongs entirely to the Brain clock. No comparison
between a Mac's monotonic clock and a remote Brain clock is required.
"""
from bisect import bisect_right
import math
from statistics import median

from agent.song_audio import finite, validate_map


class SongTimeline:
    def __init__(self, recording):
        validate_map(recording)
        self.recording = recording
        self.beats = tuple(recording['beat_seconds'])
        intervals = [right - left for left, right in zip(self.beats, self.beats[1:])]
        self.bpm = 60 / median(intervals)  # descriptive only, never the pulse clock
        self.min_interval = min(intervals)
        self.ttl = min(1., median(intervals))
        self.sample = None
        self.revision = 0
        self.discontinuity = 0
        self.stalled = False
        self._progress_anchor = None
        self._recovery_anchor = None

    def observe(self, data, sent, received):
        if (data.get('song_id') != self.recording['song_id'] or data.get('sha256') != self.recording['sha256']
                or not finite(sent) or not finite(received) or sent > received
                or not finite(data.get('position_seconds')) or data['position_seconds'] < -.1
                or data['position_seconds'] > self.recording['duration_seconds'] + .1
                or not finite(data.get('rate')) or data['rate'] != 1
                or data.get('state') not in ('playing', 'buffering', 'paused', 'ended')):
            raise ValueError('The exact recording playhead was not confirmed.')
        midpoint, uncertainty = (sent + received) / 2, (received - sent) / 2
        position = data['position_seconds']
        sample = {'position': position, 'midpoint': midpoint, 'received': received,
                  'uncertainty': uncertainty, 'state': data['state']}

        def progression(anchor):
            return (midpoint - anchor['midpoint'], position - anchor['position'],
                    .1 + uncertainty + anchor['uncertainty'])

        if data['state'] != 'playing':
            if self.sample and not self.stalled:
                self.discontinuity += 1
            self.stalled = True
            self._progress_anchor = None
            self._recovery_anchor = sample
        elif self.sample is None:
            self._progress_anchor = sample
        elif self.stalled:
            anchor = self._recovery_anchor or self.sample
            elapsed, progress, allowance = progression(anchor)
            if elapsed > 0 and (progress < 0 or abs(progress - elapsed) > allowance):
                self._recovery_anchor = sample
            elif elapsed > 0 and progress > allowance:
                # Require an observed coherent segment, not a tiny positive
                # increment or merely the player's reported playing flag.
                self.stalled = False
                self._progress_anchor = anchor
                self._recovery_anchor = None
        else:
            anchor = self._progress_anchor or self.sample
            elapsed, progress, allowance = progression(anchor)
            no_progress = (midpoint > self.sample['midpoint']
                           and position <= self.sample['position'] + 1e-6)
            if no_progress or abs(progress - elapsed) > allowance:
                self.discontinuity += 1
                self.stalled = True
                self._progress_anchor = None
                self._recovery_anchor = sample
            # Keep the original progression anchor during coherent playback:
            # resetting a tolerance on each small read could admit any slow drift.
        self.revision += 1
        self.sample = sample

    def ready(self, now):
        return (self.sample is not None and self.sample['state'] == 'playing' and not self.stalled
                and 0 <= now - self.sample['received'] <= self.ttl
                and self.sample['uncertainty'] < self.min_interval / 2)

    def position(self, now):
        return self.sample['position'] + now - self.sample['midpoint']

    def beat_number(self, position):
        index = min(max(0, bisect_right(self.beats, position) - 1), len(self.beats) - 2)
        return index + (position - self.beats[index]) / (self.beats[index + 1] - self.beats[index])

    def beat_time(self, number):
        if not finite(number) or not 0 <= number <= len(self.beats) - 1:
            return None  # never fabricate a constant-BPM tail past analyzed audio
        index = math.floor(number)
        return self.beats[index] if index == len(self.beats) - 1 else (
            self.beats[index] + (number - index) * (self.beats[index + 1] - self.beats[index]))

    def due(self, number):
        seconds = self.beat_time(number)
        return None if seconds is None else self.sample['midpoint'] + seconds - self.sample['position']

    def next_cycle(self, now, cadence):
        number = self.beat_number(self.position(now))
        return max(0, math.floor(number / (2 * cadence)) + 1)

    def status(self, now):
        return {'state': 'ready' if self.ready(now) else 'pending',
                'playhead_advancing': self.sample is not None and not self.stalled,
                'source': 'recording-derived beat positions plus live mpv audio playhead',
                'sample_age_ms': None if not self.sample else round((now - self.sample['received']) * 1000, 3),
                'sample_uncertainty_ms': None if not self.sample else round(self.sample['uncertainty'] * 1000, 3),
                'discontinuities': self.discontinuity, 'physical_alignment_verified': False}
