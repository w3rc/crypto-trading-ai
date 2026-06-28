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


def test_make_exchange_shadow_loads_credentials():
    ex = market.make_exchange("binance", "shadow", "KEY123", "SECRET456")
    assert ex.apiKey == "KEY123"
    assert ex.secret == "SECRET456"


def test_make_exchange_paper_has_no_credentials():
    ex = market.make_exchange("binance")        # 1-arg paper call unchanged
    assert not ex.apiKey                        # "" / None -> falsy


class BalanceExchange:
    def fetch_balance(self):
        return {"USDT": {"free": 5000.0, "used": 0.0, "total": 5000.0},
                "BTC": {"free": 0.25, "used": 0.0, "total": 0.25}}


def test_fetch_balance_maps_quote_and_base():
    cash, qty = market.fetch_balance(BalanceExchange(), ["BTC/USDT", "ETH/USDT"])
    assert cash == 5000.0                        # free USDT (shared quote)
    assert qty["BTC/USDT"] == 0.25
    assert qty["ETH/USDT"] == 0.0                # no ETH balance -> 0.0
