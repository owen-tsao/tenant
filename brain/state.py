from dataclasses import dataclass, field
import time
from typing import Any, Literal
from uuid import uuid4


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
    # Invitation aliases rotate; enrollment belongs to the stable room.
    room_id: str | None = None


@dataclass
class Room:
    code: str
    label: str
    device_ids: set[str] = field(default_factory=set)
    epoch: int = 0
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class PhotonBinding:
    assignment_id: str
    agent_number: str
    handle: str


@dataclass
class Lease:
    guest_id: str
    room_code: str
    state: Literal['joining', 'active', 'released', 'expired']
    scopes: set[str]
    expires_at: float
    channel: Literal['photon', 'webchat']
    photon: PhotonBinding | None
    display_name: str
    room_id: str | None = None
    joining_until: float | None = None


@dataclass
class Session:
    guest_id: str
    messages: list[dict] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
