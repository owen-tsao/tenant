"""Public, bounded operational log. Never include credentials or raw chat/planner output."""
import json
from pathlib import Path
import time


class EventLog:
    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.rows = []

    def append(self, kind, text):
        row = {'t': self.clock(), 'kind': kind, 'text': str(text)[:240]}
        self.rows.append(row)
        del self.rows[:-100]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, ensure_ascii=True) + '\n')
        return row

    def clear(self):
        self.rows.clear()
