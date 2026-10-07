"""Configuration without revealing credentials or mutating the process environment."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

ACCOUNT_BASE_URL = "https://api.binance.com"
DEFAULT_PUBLIC_BASE_URL = "https://data-api.binance.vision"
PUBLIC_BASE_URLS = (ACCOUNT_BASE_URL, DEFAULT_PUBLIC_BASE_URL)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ASSETS = ("USDT", "BTC", "ETH", "SOL")


class ConfigError(ValueError):
    """A safe configuration error; messages never include supplied values."""


@dataclass(frozen=True)
class Config:
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL
    timeout_seconds: float = 10.0
    recv_window_ms: int = 5000
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.public_base_url not in PUBLIC_BASE_URLS:
            raise ConfigError("BINANCE_PUBLIC_BASE_URL must be an official supported HTTPS host.")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 60:
            raise ConfigError("BINANCE_TIMEOUT_SECONDS must be greater than 0 and at most 60.")
        if not 1 <= self.recv_window_ms <= 5000:
            raise ConfigError("BINANCE_RECV_WINDOW_MS must be between 1 and 5000.")

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)


def load_config(
    *,
    include_credentials: bool = True,
    env_file: Path | None = Path(".env"),
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Process variables override .env, including intentionally empty values."""
    values = dict(dotenv_values(env_file, interpolate=False)) if env_file else {}
    values.update(os.environ if environ is None else environ)
    try:
        return Config(
            public_base_url=(
                values.get("BINANCE_PUBLIC_BASE_URL") or DEFAULT_PUBLIC_BASE_URL
            ).rstrip("/"),
            timeout_seconds=float(values.get("BINANCE_TIMEOUT_SECONDS") or "10"),
            recv_window_ms=int(values.get("BINANCE_RECV_WINDOW_MS") or "5000"),
            api_key=(values.get("BINANCE_API_KEY") or "").strip() if include_credentials else "",
            api_secret=(values.get("BINANCE_API_SECRET") or "").strip()
            if include_credentials
            else "",
        )
    except ValueError, TypeError:
        raise ConfigError("Invalid Binance configuration; check the documented settings.") from None
