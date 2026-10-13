"""Public Binance Spot klines, immutable raw pages and fail-closed validation."""
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

STEP = 14_400_000
BASE = 'https://data-api.binance.vision'
SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')


def request(path, params=None):
    url = BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.load(response)
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def validate(df, allow_gaps=False):
    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError('Empty data or invalid timestamp index')
    if str(df.index.tz) != 'UTC':
        raise ValueError('Timestamps must be UTC')
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError('Duplicate or unordered timestamps')
    values = df[['open', 'high', 'low', 'close', 'volume']].to_numpy()
    if not np.isfinite(values).all():
        raise ValueError('Non-finite OHLCV')
    if (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
        raise ValueError('Non-positive price or negative volume')
    if ((df.high < df[['open', 'close', 'low']].max(axis=1)) |
            (df.low > df[['open', 'close', 'high']].min(axis=1))).any():
        raise ValueError('Invalid OHLC geometry')
    stamps = df.index.as_unit('ms').asi8
    if (stamps % STEP != 0).any():
        raise ValueError('Off-grid 4H timestamps')
    if not allow_gaps and len(stamps) > 1 and (np.diff(stamps) != STEP).any():
        raise ValueError('Missing 4H candles; no forward fill permitted')


def clean(rows, cutoff):
    records = []
    removed = 0
    for row in rows:
        stamp = int(row[0])
        if stamp >= cutoff:
            removed += 1
            continue
        if not stamp <= int(row[6]) < stamp + STEP:
            raise ValueError('Unexpected close timestamp')
        records.append([stamp] + [float(v) for v in row[1:6]])
    df = pd.DataFrame(records, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    duplicate_count = int(df.timestamp.duplicated().sum())
    for _, group in df[df.timestamp.duplicated(False)].groupby('timestamp'):
        if len(group.drop_duplicates()) > 1:
            raise ValueError('Conflicting duplicate candles')
    df = df.drop_duplicates().sort_values('timestamp')
    df.index = pd.to_datetime(df.pop('timestamp'), unit='ms', utc=True)
    validate(df, allow_gaps=True)
    if int(df.index[-1].value // 1_000_000) + STEP != cutoff:
        raise ValueError('Data does not reach last confirmed candle')
    stamps = df.index.as_unit('ms').asi8
    gaps = [{'after': str(df.index[i]), 'before': str(df.index[i+1]),
             'missing': int((stamps[i+1]-stamps[i])//STEP-1)}
            for i in range(len(stamps)-1) if stamps[i+1]-stamps[i] != STEP]
    return df, {'identical_duplicates_removed': duplicate_count, 'unconfirmed_removed': removed,
                'gaps': gaps, 'short_close_timestamps': sum(int(r[6]) != int(r[0])+STEP-1 for r in rows)}


def collect(root):
    root = Path(root)
    raw = root / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    meta_path = root / 'snapshot.json'
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        now = request('/api/v3/time')['serverTime']
        meta = {'source': BASE, 'server_time_ms': now, 'cutoff_ms': now // STEP * STEP,
                'interval': '4h', 'market': 'Binance Spot', 'symbols': list(SYMBOLS)}
        meta_path.write_text(json.dumps(meta, indent=2))
    cutoff = meta['cutoff_ms']
    frames, reports = {}, {}
    for symbol in SYMBOLS:
        cursor, rows, pages = 0, [], []
        while cursor < cutoff:
            dest = raw / f'{symbol}_{cursor}.json'
            if dest.exists():
                content = dest.read_bytes()
                batch = json.loads(content)
            else:
                batch = request('/api/v3/klines', {'symbol': symbol, 'interval': '4h',
                                'startTime': cursor, 'endTime': cutoff - 1, 'limit': 1000})
                content = json.dumps(batch, separators=(',', ':')).encode()
                dest.write_bytes(content)
                time.sleep(0.12)
            if not batch:
                raise ValueError(f'{symbol}: unexpected empty page at {cursor}')
            pages.append({'file': dest.name, 'sha256': hashlib.sha256(content).hexdigest(), 'rows': len(batch)})
            rows.extend(batch)
            new_cursor = int(batch[-1][0]) + STEP
            if new_cursor <= cursor:
                raise ValueError('Pagination did not advance')
            cursor = new_cursor
        df, report = clean(rows, cutoff)
        # Re-query each hole. Empty responses remain explicit source gaps.
        for gap in report['gaps']:
            begin = int(pd.Timestamp(gap['after']).value // 1_000_000) + STEP
            finish = int(pd.Timestamp(gap['before']).value // 1_000_000) - 1
            repair = request('/api/v3/klines', {'symbol': symbol, 'interval': '4h',
                             'startTime': begin, 'endTime': finish, 'limit': 1000})
            dest = raw / f'{symbol}_repair_{begin}.json'
            content = json.dumps(repair).encode()
            dest.write_bytes(content)
            pages.append({'file': dest.name, 'sha256': hashlib.sha256(content).hexdigest(), 'rows': len(repair)})
            rows.extend(repair)
        df, report = clean(rows, cutoff)
        # Independently verify exchange's earliest available bar (listing boundary).
        earliest = request('/api/v3/klines', {'symbol': symbol, 'interval': '4h', 'startTime': 0, 'limit': 1})
        if int(earliest[0][0]) != int(df.index[0].value // 1_000_000):
            raise ValueError('Full-history listing boundary mismatch')
        dest = root / f'{symbol}_4h.csv'
        df.to_csv(dest)
        report.update({'status': 'PASS_WITH_DOCUMENTED_GAPS' if report['gaps'] else 'PASS', 'rows': len(df), 'first': str(df.index[0]),
                       'last': str(df.index[-1]), 'missing_bars': sum(g['missing'] for g in report['gaps']), 'pages': pages,
                       'clean_sha256': hashlib.sha256(dest.read_bytes()).hexdigest()})
        frames[symbol], reports[symbol] = df, report
        (root / 'validation.json').write_text(json.dumps(reports, indent=2))
        print(f"{symbol}: {report['status']} {len(df)} confirmed bars {df.index[0]} .. {df.index[-1]}", flush=True)
    return frames, meta
