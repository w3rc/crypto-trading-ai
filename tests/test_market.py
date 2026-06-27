from engine.market import fetch_ohlcv_df, fetch_price

class FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe, limit):
        # ccxt returns [ts, open, high, low, close, volume]
        return [[i, 100 + i, 101 + i, 99 + i, 100 + i, 5.0] for i in range(limit)]
    def fetch_ticker(self, symbol):
        return {"last": 123.45}

def test_fetch_ohlcv_df_shape():
    df = fetch_ohlcv_df(FakeExchange(), "BTC/USDT", "15m", limit=60)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 60
    assert df["close"].iloc[-1] == 159

def test_fetch_price():
    assert fetch_price(FakeExchange(), "BTC/USDT") == 123.45


from types import SimpleNamespace
from engine import market


def test_supports_short_spot_is_false():
    assert market.supports_short(SimpleNamespace(options={"defaultType": "spot"})) is False


def test_supports_short_swap_is_true():
    assert market.supports_short(SimpleNamespace(options={"defaultType": "swap"})) is True
    assert market.supports_short(SimpleNamespace(options={"defaultType": "future"})) is True


def test_supports_short_unknown_or_none_is_false():
    assert market.supports_short(SimpleNamespace()) is False   # no .options
    assert market.supports_short(None) is False
