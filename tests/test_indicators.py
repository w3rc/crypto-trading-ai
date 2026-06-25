import pandas as pd
import pytest
from engine.indicators import compute_indicators

def _df(closes):
    return pd.DataFrame({
        "open": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [100.0] * len(closes),
    })

def test_rising_series_is_overbought_and_trending_up():
    f = compute_indicators(_df([100.0 + i for i in range(60)]))
    assert f["rsi"] > 70          # only gains -> RSI near 100
    assert f["macd"] > 0          # fast EMA above slow EMA
    assert f["ma_fast"] > f["ma_slow"]
    assert f["atr"] > 0
    assert f["price"] == 159.0    # last close

def test_falling_series_is_oversold():
    f = compute_indicators(_df([200.0 - i for i in range(60)]))
    assert f["rsi"] < 30
    assert f["macd"] < 0

def test_too_few_rows_raises():
    with pytest.raises(ValueError):
        compute_indicators(_df([100.0 + i for i in range(10)]))
