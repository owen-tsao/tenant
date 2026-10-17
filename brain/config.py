from dataclasses import dataclass
import os

@dataclass
class Config:
    device_token: str
    host_token: str
    room_code: str = "7F3A"
    public_url: str = "http://localhost:8000"

    @classmethod
    def from_env(cls):
        return cls(os.getenv("DEVICE_TOKEN", ""), os.getenv("HOST_TOKEN", ""),
                   os.getenv("ROOM_CODE", "7F3A"), os.getenv("PUBLIC_URL", "http://localhost:8000"))
