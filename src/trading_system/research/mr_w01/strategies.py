"""Actual frozen BaseStrategy interface, with SMA-seeded Wilder indicators for MR."""

import numpy as np
import pandas as pd

from trading_system.observer.frozen.alpha_lab.data import validate
from trading_system.observer.frozen.alpha_lab.strategies import BaseStrategy


def wilder(values: pd.Series, period: int) -> pd.Series:
    """Seed with the first period's arithmetic mean, then Wilder recurrence."""
    result = np.full(len(values), np.nan)
    first = values.first_valid_index()
    if first is None:
        return pd.Series(result, index=values.index)
    start = values.index.get_loc(first)
    seed = start + period - 1
    if len(values) <= seed:
        return pd.Series(result, index=values.index)
    raw = values.to_numpy(dtype=float)
    result[seed] = raw[start : seed + 1].mean()
    for i in range(seed + 1, len(values)):
        result[i] = (result[i - 1] * (period - 1) + raw[i]) / period
    return pd.Series(result, index=values.index)


class MeanReversion(BaseStrategy):
    atr_stop_multiple = 2.5

    @property
    def warmup_bars(self):
        # Match W01's common initialization/evaluation boundary, not an optimized warmup.
        return 201

    def generate(self, ohlcv):
        self._validate_ohlcv(ohlcv)
        validate(ohlcv)
        if "is_closed" in ohlcv and not ohlcv.is_closed.eq(True).all():
            raise ValueError("Unconfirmed candle")
        df = ohlcv.copy()
        previous = df.close.shift(1)
        tr = pd.concat(
            [df.high - df.low, (df.high - previous).abs(), (df.low - previous).abs()],
            axis=1,
        ).max(axis=1)
        df["atr"] = wilder(tr, 20)
        df["ema200"] = df.close.ewm(span=200, adjust=False, min_periods=200).mean()
        df = self._add_indicators(df)
        entry, exit_ = self._generate_signals(df)
        df["entry_long"] = entry.fillna(False).astype(bool)
        df["exit_long"] = exit_.fillna(False).astype(bool)
        df.iloc[: self.warmup_bars, df.columns.get_indexer(["entry_long", "exit_long"])] = False
        df["entry_atr"] = df.atr.where(df.entry_long)
        return df


class RSIReversion(MeanReversion):
    strategy_id = "meanrev_rsi"

    def _add_indicators(self, df):
        change = df.close.diff()
        gain = wilder(change.clip(lower=0), 14)
        loss = wilder(-change.clip(upper=0), 14)
        df["rsi14"] = 100 - 100 / (1 + gain / loss)
        # A flat series is neutral; gains without losses imply RSI 100.
        df.loc[(gain == 0) & (loss == 0), "rsi14"] = 50.0
        return df

    def _generate_signals(self, df):
        entry = (df.close > df.ema200) & (df.rsi14.shift(1) < 30) & (df.rsi14 >= 30)
        return entry, df.rsi14 >= 50


class BollingerReversion(MeanReversion):
    strategy_id = "meanrev_bollinger"

    def _add_indicators(self, df):
        df["sma20"] = df.close.rolling(20).mean()
        df["lower_band"] = df.sma20 - 2 * df.close.rolling(20).std(ddof=0)
        return df

    def _generate_signals(self, df):
        entry = (
            (df.close > df.ema200)
            & (df.close.shift(1) < df.lower_band.shift(1))
            & (df.close >= df.lower_band)
        )
        return entry, df.close >= df.sma20


class ShockReversal(BollingerReversion):
    strategy_id = "meanrev_shock"

    def _add_indicators(self, df):
        df["sma20"] = df.close.rolling(20).mean()
        df["r3"] = df.close / df.close.shift(3) - 1
        df["r3_std60"] = df.r3.rolling(60).std(ddof=0)
        return df

    def _generate_signals(self, df):
        entry = (
            (df.r3.shift(1) <= -2 * df.r3_std60.shift(1))
            & (df.close > df.close.shift(1))
            & (df.close > df.ema200)
        )
        return entry, df.close >= df.sma20


REGISTRY = {s.key: s for s in (RSIReversion(), BollingerReversion(), ShockReversal())}
