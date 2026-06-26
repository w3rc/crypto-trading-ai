import os

import pandas as pd

COLS = ["ts", "open", "high", "low", "close", "volume"]


def _cache_path(cache_dir, exchange_name, symbol, timeframe):
    safe = symbol.replace("/", "-")
    return os.path.join(cache_dir, f"{exchange_name}_{safe}_{timeframe}.csv")


def _read_cache(path):
    if os.path.exists(path):
        return pd.read_csv(path)
    return pd.DataFrame(columns=COLS)


def _write_cache(path, df):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _covers(df, since_ms, until_ms):
    return not df.empty and df["ts"].min() <= since_ms and df["ts"].max() >= until_ms


def _fetch_range(exchange, symbol, timeframe, since_ms, until_ms, limit=1000):
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    rows = []
    cursor = since_ms
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        cursor = batch[-1][0] + tf_ms
        if len(batch) < limit:
            break
    df = pd.DataFrame(rows, columns=COLS)
    return df[df["ts"] <= until_ms]


def _merge(cached, fetched):
    df = pd.concat([cached, fetched], ignore_index=True)
    return df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)


def load_ohlcv(exchange, symbol, timeframe, since_ms, until_ms, cache_dir="data/cache"):
    exchange_name = getattr(exchange, "id", "exchange")
    path = _cache_path(cache_dir, exchange_name, symbol, timeframe)
    cached = _read_cache(path)
    if not _covers(cached, since_ms, until_ms):
        # ponytail: re-fetches the whole requested range on a partial-coverage
        # miss, not just the gap; gap-only fetch is the upgrade path.
        fetched = _fetch_range(exchange, symbol, timeframe, since_ms, until_ms)
        cached = _merge(cached, fetched)
        _write_cache(path, cached)
    out = cached[(cached["ts"] >= since_ms) & (cached["ts"] <= until_ms)]
    return out.reset_index(drop=True)
