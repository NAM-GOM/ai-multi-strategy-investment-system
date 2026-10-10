"""Execution safety settings are independent of W03 Frozen parameters."""

import os
from dataclasses import dataclass
from decimal import Decimal

from trading_system.testnet.client import TestnetConfig as IsolatedConfig
from trading_system.testnet.client import TestnetError

T1 = "trend_ma_v0.1"
EXPERIMENT = "MAINNET_SIGNAL_TESTNET_EXECUTION_EXPERIMENT"


class TestnetConfig(IsolatedConfig):
    __test__ = False

    @classmethod
    def from_env(cls):
        config = super().from_env()
        if (config.api_key and config.api_key == os.environ.get("BINANCE_API_KEY")) or (
            config.api_secret and config.api_secret == os.environ.get("BINANCE_API_SECRET")
        ):
            raise TestnetError("PRODUCTION_CREDENTIAL_REUSE_DENIED")
        return config


@dataclass(frozen=True)
class SafetyConfig:
    max_signal_age_ms: int = 60_000
    max_quote_age_ms: int = 5_000
    max_reference_age_ms: int = 30_000
    max_price_difference: Decimal = Decimal("0.02")
    max_spread: Decimal = Decimal("0.005")
    automated_enabled: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            automated_enabled=os.environ.get("BINANCE_TESTNET_AUTOMATED_ENABLED")
            == "YES_T1_TESTNET_ONLY"
        )


__all__ = ["EXPERIMENT", "T1", "SafetyConfig", "TestnetConfig"]
