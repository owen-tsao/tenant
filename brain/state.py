from dataclasses import dataclass, field
import time
from typing import Any

@dataclass
class CapSpec:
    name: str
    args: dict
    description: str

@dataclass
class Device:
    id: str
    label: str
    room_code: str
    caps: dict[str, CapSpec]
    ws: Any
    last_seen: float = field(default_factory=time.monotonic)
    busy: bool = False
    online: bool = True

@dataclass
class Room:
    code: str
    label: str
    device_ids: set[str] = field(default_factory=set)
    epoch: int = 0
