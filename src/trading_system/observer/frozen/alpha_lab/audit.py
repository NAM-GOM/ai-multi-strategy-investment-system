"""Independent post-run accounting and risk checks against saved ledgers."""
import numpy as np
import pandas as pd


def audit(ledger, curve, initial=100000.):
    if (curve.cash < -1e-7).any():
        raise AssertionError('Negative cash')
    np.testing.assert_allclose(curve.equity, curve.cash + curve.position_value, rtol=1e-11, atol=1e-6)
    if len(ledger):
        if (ledger.quantity <= 0).any():
            raise AssertionError('Short or zero position')
        if (ledger.quantity * ledger.entry_fill > ledger.entry_equity * .333 + 1e-6).any():
            raise AssertionError('Entry allocation cap exceeded')
        if (ledger.quantity * 3 * ledger.entry_atr > ledger.entry_equity * .005 + 1e-6).any():
            raise AssertionError('Entry stop-distance risk exceeded')
        np.testing.assert_allclose(ledger.initial_stop, ledger.entry_fill - 3 * ledger.entry_atr)
        np.testing.assert_allclose(ledger.entry_fee, ledger.quantity * ledger.entry_fill * .001)
        np.testing.assert_allclose(ledger.exit_fee, ledger.quantity * ledger.exit_fill * .001)
        np.testing.assert_allclose(ledger.entry_fill, ledger.entry_price_raw * 1.0005)
        np.testing.assert_allclose(ledger.exit_fill, ledger.exit_price_raw * .9995)
        np.testing.assert_allclose(ledger.net_pnl, ledger.quantity * (ledger.exit_fill - ledger.entry_fill) - ledger.entry_fee - ledger.exit_fee)
        if not (pd.to_datetime(ledger.signal_time, utc=True) == pd.to_datetime(ledger.entry_time, utc=True)).all():
            raise AssertionError('Entry is not next open after signal confirmation')
        normal = ledger[ledger.exit_reason == 'SIGNAL']
        if not (pd.to_datetime(normal.exit_signal_time, utc=True) == pd.to_datetime(normal.exit_time, utc=True)).all():
            raise AssertionError('Exit is not next open after signal confirmation')
        for _, trades in ledger.groupby('symbol'):
            trades = trades.sort_values('entry_time')
            entry = pd.to_datetime(trades.entry_time, utc=True).reset_index(drop=True)
            exit = pd.to_datetime(trades.exit_time, utc=True).reset_index(drop=True)
            if len(trades) > 1 and (entry.iloc[1:].reset_index(drop=True) < exit.iloc[:-1].reset_index(drop=True)).any():
                raise AssertionError('Overlapping positions / pyramiding')
        np.testing.assert_allclose(curve.equity.iloc[-1], initial + ledger.net_pnl.sum(), atol=1e-5)
        np.testing.assert_allclose(curve.fees.iloc[-1], ledger.entry_fee.sum() + ledger.exit_fee.sum(), atol=1e-5)
    return {'status': 'PASS', 'trades_checked': len(ledger), 'equity_rows_checked': len(curve),
            'checks': ['cash', 'equity identity', 'entry cap', 'entry risk', 'frozen stop',
                       'fee and slippage', 'net PnL', 'next-open timing', 'no pyramiding', 'terminal reconciliation']}
