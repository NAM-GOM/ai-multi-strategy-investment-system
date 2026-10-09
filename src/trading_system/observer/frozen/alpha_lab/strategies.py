from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


# ============================================================
# Common indicator
# ============================================================

def wilder_atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    Wilder-style ATR approximation using exponentially weighted smoothing.

    Only current/past data is used.
    """
    prev_close = df["close"].shift(1)

    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


# ============================================================
# Base interface
# ============================================================

class BaseStrategy(ABC):
    """
    Strategy responsibility:
        - calculate indicators
        - generate entry/exit signals

    Backtest engine responsibility:
        - order execution
        - fees/slippage
        - stop execution
        - position sizing
        - portfolio accounting
    """

    strategy_id: str
    version: str = "0.1"

    atr_period: int = 20
    atr_stop_multiple: float = 3.0

    @property
    def key(self) -> str:
        return f"{self.strategy_id}_v{self.version}"

    @property
    @abstractmethod
    def warmup_bars(self) -> int:
        """Minimum number of candles required before valid signals."""
        raise NotImplementedError

    @abstractmethod
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    @abstractmethod
    def _generate_signals(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.Series]:
        raise NotImplementedError

    def generate(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        self._validate_ohlcv(ohlcv)

        df = ohlcv.copy()

        df["atr"] = wilder_atr(
            df,
            period=self.atr_period,
        )

        df = self._add_indicators(df)

        entry_long, exit_long = self._generate_signals(df)

        df["entry_long"] = (
            entry_long.fillna(False).astype(bool)
        )

        df["exit_long"] = (
            exit_long.fillna(False).astype(bool)
        )

        # ATR value frozen on signal candle.
        # Used by engine after next-bar entry.
        df["entry_atr"] = df["atr"].where(
            df["entry_long"]
        )

        return df

    @staticmethod
    def _validate_ohlcv(df: pd.DataFrame) -> None:
        required = {
            "open",
            "high",
            "low",
            "close",
            "volume",
        }

        missing = required - set(df.columns)

        if missing:
            raise ValueError(
                f"Missing OHLCV columns: {missing}"
            )

        if not isinstance(df.index, pd.DatetimeIndex):
            raise TypeError(
                "OHLCV index must be DatetimeIndex."
            )

        if not df.index.is_monotonic_increasing:
            raise ValueError(
                "OHLCV index must be sorted ascending."
            )

        if df.index.has_duplicates:
            raise ValueError(
                "OHLCV index contains duplicates."
            )

@dataclass(frozen=True)
class MATrendConfig:
    fast_ema: int = 50
    slow_ema: int = 200


class MATrendStrategy(BaseStrategy):

    strategy_id = "trend_ma"

    def __init__(
        self,
        config: MATrendConfig = MATrendConfig(),
    ):
        if config.fast_ema >= config.slow_ema:
            raise ValueError(
                "fast_ema must be smaller than slow_ema."
            )

        self.config = config

    @property
    def warmup_bars(self) -> int:
        return max(
            self.config.slow_ema,
            self.atr_period,
        ) + 1

    def _add_indicators(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        df["ema_fast"] = df["close"].ewm(
            span=self.config.fast_ema,
            adjust=False,
            min_periods=self.config.fast_ema,
        ).mean()

        df["ema_slow"] = df["close"].ewm(
            span=self.config.slow_ema,
            adjust=False,
            min_periods=self.config.slow_ema,
        ).mean()

        return df

    def _generate_signals(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.Series]:

        fast = df["ema_fast"]
        slow = df["ema_slow"]

        entry_long = (
            (fast > slow)
            & (fast.shift(1) <= slow.shift(1))
        )

        exit_long = (
            (fast < slow)
            & (fast.shift(1) >= slow.shift(1))
        )

        return entry_long, exit_long

@dataclass(frozen=True)
class DonchianConfig:
    entry_lookback: int = 55
    exit_lookback: int = 20


class DonchianTrendStrategy(BaseStrategy):

    strategy_id = "trend_donchian"

    def __init__(
        self,
        config: DonchianConfig = DonchianConfig(),
    ):
        if config.exit_lookback >= config.entry_lookback:
            raise ValueError(
                "exit_lookback must be smaller "
                "than entry_lookback."
            )

        self.config = config

    @property
    def warmup_bars(self) -> int:
        return max(
            self.config.entry_lookback,
            self.atr_period,
        ) + 1

    def _add_indicators(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        # IMPORTANT:
        # shift(1) excludes current candle.
        df["donchian_upper"] = (
            df["high"]
            .shift(1)
            .rolling(
                self.config.entry_lookback,
                min_periods=self.config.entry_lookback,
            )
            .max()
        )

        df["donchian_lower"] = (
            df["low"]
            .shift(1)
            .rolling(
                self.config.exit_lookback,
                min_periods=self.config.exit_lookback,
            )
            .min()
        )

        return df

    def _generate_signals(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.Series]:

        entry_long = (
            df["close"] > df["donchian_upper"]
        )

        exit_long = (
            df["close"] < df["donchian_lower"]
        )

        return entry_long, exit_long

@dataclass(frozen=True)
class TSMOMConfig:
    lookback: int = 180


class TSMOMTrendStrategy(BaseStrategy):

    strategy_id = "trend_tsmom"

    def __init__(
        self,
        config: TSMOMConfig = TSMOMConfig(),
    ):
        self.config = config

    @property
    def warmup_bars(self) -> int:
        # Current momentum + previous momentum required.
        return max(
            self.config.lookback + 2,
            self.atr_period,
        )

    def _add_indicators(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        df["momentum"] = (
            df["close"]
            / df["close"].shift(self.config.lookback)
            - 1.0
        )

        return df

    def _generate_signals(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.Series, pd.Series]:

        momentum = df["momentum"]

        entry_long = (
            (momentum > 0)
            & (momentum.shift(1) <= 0)
        )

        exit_long = (
            (momentum < 0)
            & (momentum.shift(1) >= 0)
        )

        return entry_long, exit_long

STRATEGY_REGISTRY = {
    "trend_ma_v0.1": MATrendStrategy(),

    "trend_donchian_v0.1": (
        DonchianTrendStrategy()
    ),

    "trend_tsmom_v0.1": (
        TSMOMTrendStrategy()
    ),
}

