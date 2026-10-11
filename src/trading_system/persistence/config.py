import math
from dataclasses import dataclass
from pathlib import Path


def database_path(value: str | Path) -> Path:
    text = str(value)
    if not text or any(c in text for c in ("\x00", "\n", "\r", "?", "#")):
        raise ValueError("Invalid local database path.")
    if text.startswith(("file:", "//", "\\\\")) or text == ":memory:":
        raise ValueError("A local disk database is required.")
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() not in (".sqlite", ".sqlite3", ".db") or path.is_dir():
        raise ValueError("Database path must be a local .sqlite/.sqlite3/.db file.")
    return path


@dataclass(frozen=True)
class PersistenceConfig:
    db_path: str | Path = "data/market_data.sqlite"
    bootstrap_days: int = 7
    snapshot_seconds: int = 60
    retention_days: int = 30
    recovery_max_days: int = 365
    max_rest_requests: int = 32
    rest_interval_seconds: float = 0.25
    rest_retries: int = 1
    recovery_interval_seconds: float = 60

    def __post_init__(self):
        object.__setattr__(self, "db_path", database_path(self.db_path))
        for value, maximum in (
            (self.bootstrap_days, 365),
            (self.snapshot_seconds, 3600),
            (self.retention_days, 3650),
            (self.recovery_max_days, 3650),
            (self.max_rest_requests, 1000),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Persistence integer settings outside supported bounds.")
        if self.bootstrap_days > self.recovery_max_days:
            raise ValueError("Bootstrap range exceeds recovery range limit.")
        if type(self.rest_retries) is not int or not 0 <= self.rest_retries <= 2:
            raise ValueError("REST retry count must be 0..2.")
        if (
            not math.isfinite(self.rest_interval_seconds)
            or not 0.05 <= self.rest_interval_seconds <= 10
        ):
            raise ValueError("REST request interval must be 0.05..10s.")
        if not math.isfinite(self.recovery_interval_seconds) or self.recovery_interval_seconds < 5:
            raise ValueError("Recovery interval must be at least 5s.")
