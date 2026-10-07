"""Account authentication and four balances; no state-changing endpoints."""

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from trading_system.binance.client import BinanceClient, BinanceError
from trading_system.binance.public import amount
from trading_system.config import ASSETS

logger = logging.getLogger("trading_system.account")
MISSING_CREDENTIALS = "Private API credentials not configured. Account check skipped."


@dataclass(frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal

    @property
    def total(self) -> Decimal:
        return self.free + self.locked


class AccountAPI:
    def __init__(self, client: BinanceClient) -> None:
        self.client = client

    def balances(self) -> tuple[Balance, ...] | None:
        if not self.client.config.has_credentials:
            logger.info("account authentication skipped: credentials not configured")
            return None
        try:
            response = self.client.get("/api/v3/account", signed=True)
            try:
                rows = response.data["balances"]
                if not isinstance(rows, list):
                    raise ValueError
                by_asset = {}
                for row in rows:
                    asset = row["asset"]
                    if asset in ASSETS:
                        if asset in by_asset:
                            raise ValueError
                        by_asset[asset] = Balance(asset, amount(row["free"]), amount(row["locked"]))
                result = tuple(
                    by_asset.get(asset, Balance(asset, Decimal(0), Decimal(0))) for asset in ASSETS
                )
            except KeyError, TypeError, ValueError, InvalidOperation:
                raise BinanceError("invalid_response", "/api/v3/account") from None
        except BinanceError as error:
            logger.error("account authentication failure exception=%s", error)
            raise
        logger.info("account authentication success latency_ms=%.3f", response.latency_ms)
        return result
