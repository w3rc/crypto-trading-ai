import pandas as pd
from engine import datafeed

COLS = ["ts", "open", "high", "low", "close", "volume"]
TF_MS = 3_600_000  # 1h


def _candles(n, start=0):
    return [[start + i * TF_MS, 100.0 + i, 101.0 + i, 99.0 + i, 100.0 + i, 5.0]
            for i in range(n)]


class FakeExchange:
    id = "fake"

    def __init__(self, candles):
        self.candles = candles
        self.calls = 0

    def parse_timeframe(self, timeframe):
        return 3600  # seconds

    def fetch_ohlcv(self, symbol, timeframe, since=0, limit=1000):
        self.calls += 1
        rows = [r for r in self.candles if r[0] >= since]
        return rows[:limit]


def test_fetch_range_paginates(monkeypatch):
    ex = FakeExchange(_candles(5))
    df = datafeed._fetch_range(ex, "BTC/USDT", "1h", 0, 5 * TF_MS, limit=2)
    assert list(df["ts"]) == [i * TF_MS for i in range(5)]  # all 5 stitched
    assert ex.calls == 3                                    # 2 + 2 + 1


def test_load_ohlcv_cache_miss_then_hit(tmp_path):
    ex = FakeExchange(_candles(5))
    cache = str(tmp_path / "cache")
    df1 = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 4 * TF_MS, cache_dir=cache)
    assert len(df1) == 5 and ex.calls >= 1
    # second call for the same range hits the cache file — no new fetch
    calls_before = ex.calls
    df2 = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 4 * TF_MS, cache_dir=cache)
    assert ex.calls == calls_before        # no extra fetch
    assert list(df2["ts"]) == list(df1["ts"])


def test_load_ohlcv_slices_to_range(tmp_path):
    ex = FakeExchange(_candles(5))
    cache = str(tmp_path / "cache")
    df = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", TF_MS, 3 * TF_MS, cache_dir=cache)
    assert list(df["ts"]) == [TF_MS, 2 * TF_MS, 3 * TF_MS]  # only the requested window


def test_load_ohlcv_cache_hit_within_one_bar(tmp_path):
    """Cache covering ts 0..4*TF_MS must serve a request ending at 5*TF_MS-1 without fetching."""
    ex = FakeExchange(_candles(5))  # candles at 0, TF_MS, 2*TF_MS, 3*TF_MS, 4*TF_MS
    cache = str(tmp_path / "cache")
    # prime the cache
    path = datafeed._cache_path(cache, "fake", "BTC/USDT", "1h")
    import os
    os.makedirs(cache, exist_ok=True)
    pd.DataFrame(_candles(5), columns=COLS).to_csv(path, index=False)
    # request end is within one bar of the cache max — must hit, no fetch
    df = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 5 * TF_MS - 1, cache_dir=cache)
    assert ex.calls == 0, "expected cache hit but exchange was called"
    assert list(df["ts"]) == [i * TF_MS for i in range(5)]


def test_merge_dedupes_and_sorts(tmp_path):
    ex = FakeExchange(_candles(5))
    cache = str(tmp_path / "cache")
    # prime the cache with the first 3 candles only
    path = datafeed._cache_path(cache, "fake", "BTC/USDT", "1h")
    import os
    os.makedirs(cache, exist_ok=True)
    pd.DataFrame(_candles(3), columns=COLS).to_csv(path, index=False)
    # request beyond cache -> fetch + merge, no duplicate ts
    df = datafeed.load_ohlcv(ex, "BTC/USDT", "1h", 0, 4 * TF_MS, cache_dir=cache)
    assert list(df["ts"]) == [i * TF_MS for i in range(5)]
    assert df["ts"].is_unique
