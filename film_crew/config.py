"""Local OBS credentials for the supervised film-crew experiment."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat

from film_crew.cameras import DEFAULT_RUNTIME_DIR


class ConfigError(ValueError):
    """A configuration error that never includes credentials."""


@dataclass(frozen=True)
class ObsConfig:
    host: str = '127.0.0.1'
    port: int = 4455
    password: str = field(default='', repr=False)
    collection: str = 'Tenant Film Crew'

    def __post_init__(self):
        if (self.host not in {'127.0.0.1', 'localhost', '::1'}
                or type(self.port) is not int or not 1024 <= self.port <= 65535
                or not isinstance(self.password, str) or not self.password
                or len(self.password) > 1024
                or self.collection != 'Tenant Film Crew'):
            raise ConfigError('Use authenticated local OBS and the dedicated film-crew collection.')


def load_obs_config(path: str | Path = DEFAULT_RUNTIME_DIR / 'obs.json') -> ObsConfig:
    """Read a small, private credential file; do not connect or print secrets."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 8192:
                raise ValueError
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError
                    result[key] = value
                return result
            value = json.loads(stream.read(8193), object_pairs_hook=unique)
        if (not isinstance(value, dict) or not {'host', 'port', 'password'} <= value.keys()
                or value.keys() - {'host', 'port', 'password', 'collection'}):
            raise ValueError
        return ObsConfig(**value)
    except (OSError, ValueError, TypeError, UnicodeError):
        raise ConfigError('OBS configuration is missing or invalid; prepare its private local file.') from None
