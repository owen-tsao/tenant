"""Public sentences and private correlation metadata; never log credentials/chat."""
import json
import os
from pathlib import Path
import time


class EventLog:
    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.rows = []
        self.audit_rows = []

    def append(self, kind, text, **audit):
        row = {'t': self.clock(), 'kind': kind, 'text': str(text)[:240]}
        self.rows.append(row)
        del self.rows[:-100]
        private = dict(row, audit=audit) if audit else dict(row)
        self.audit_rows.append(private)
        del self.audit_rows[:-1000]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(descriptor, 'a', encoding='utf-8') as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(json.dumps(private, ensure_ascii=True) + '\n')
        return row

    def clear(self):
        self.rows.clear()
