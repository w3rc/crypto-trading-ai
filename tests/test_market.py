from engine.market import fetch_ohlcv_df, fetch_price
from engine.models import Fill

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


def test_make_exchange_hyperliquid_live_loads_wallet_creds():
    ex = market.make_exchange("hyperliquid", "live", wallet="0xabc", private_key="0xpk")
    assert ex.walletAddress == "0xabc"
    assert ex.privateKey == "0xpk"


def test_make_exchange_binance_live_loads_api_creds():
    ex = market.make_exchange("binance", "live", "KEY", "SEC")
    assert ex.apiKey == "KEY"
    assert ex.secret == "SEC"


def test_make_exchange_paper_has_no_hl_credentials():
    ex = market.make_exchange("hyperliquid")   # paper -> keyless public data
    assert not getattr(ex, "walletAddress", "")
    assert not getattr(ex, "privateKey", "")


def test_make_exchange_testnet_uses_sandbox_urls():
    ex = market.make_exchange("hyperliquid", "live", wallet="0xabc", private_key="0xpk", testnet=True)
    assert "testnet" in str(ex.urls["api"])


class BalanceExchange:
    def fetch_balance(self):
        return {"USDT": {"free": 5000.0, "used": 0.0, "total": 5000.0},
                "BTC": {"free": 0.25, "used": 0.0, "total": 0.25}}


def test_fetch_balance_maps_quote_and_base():
    cash, qty = market.fetch_balance(BalanceExchange(), ["BTC/USDT", "ETH/USDT"])
    assert cash == 5000.0                        # free USDT (shared quote)
    assert qty["BTC/USDT"] == 0.25
    assert qty["ETH/USDT"] == 0.0                # no ETH balance -> 0.0


def test_make_exchange_live_loads_credentials():
    ex = market.make_exchange("binance", "live", "LKEY", "LSEC")
    assert ex.apiKey == "LKEY" and ex.secret == "LSEC"


class _FilledExchange:
    def __init__(self):
        self.calls = []
    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        self.calls.append((symbol, order_type, side, amount))
        return {"id": "1", "status": "closed", "filled": amount,
                "average": 64010.0, "fee": {"cost": 0.64, "currency": "USDT"}}


def test_create_order_reconciles_filled_market_order():
    ex = _FilledExchange()
    fill = market.create_order(ex, "BTC/USDT", "buy", 0.01, 64000.0, "T")
    assert ex.calls == [("BTC/USDT", "market", "buy", 0.01)]   # real MARKET order
    assert isinstance(fill, Fill)
    assert fill.qty == 0.01 and fill.price == 64010.0 and fill.fee == 0.64
    assert fill.symbol == "BTC/USDT" and fill.side == "buy" and fill.ts == "T"


class _AsyncExchange:
    """Returns 'open' with no fill detail, then a closed order on fetch_order."""
    def __init__(self):
        self.fetch_calls = []
    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        return {"id": "9", "status": "open", "filled": 0.0}
    def fetch_order(self, oid, symbol):
        self.fetch_calls.append((oid, symbol))
        return {"id": oid, "status": "closed", "filled": 0.02, "average": 159.5, "fee": {"cost": 0.16}}


def test_create_order_repolls_when_not_filled():
    ex = _AsyncExchange()
    fill = market.create_order(ex, "SOL/USDT", "buy", 0.02, 159.0, "T")
    assert fill.qty == 0.02 and fill.price == 159.5 and fill.fee == 0.16
    assert ex.fetch_calls == [("9", "SOL/USDT")]


class _ErrorRepollExchange:
    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        return {"id": "7", "status": "open", "filled": 0.0}
    def fetch_order(self, oid, symbol):
        raise RuntimeError("429 rate limit")


def test_create_order_repoll_failure_falls_back(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        fill = market.create_order(_ErrorRepollExchange(), "BTC/USDT", "buy", 0.01, 64000.0, "T")
    assert fill.qty == 0.0 and fill.price == 64000.0 and fill.fee == 0.0   # falls back to original o + ref_price
    assert "re-poll failed" in caplog.text                                  # failure is observable


class _NoAvgExchange:
    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        return {"id": "2", "status": "closed", "filled": amount}   # no average, no fee


def test_create_order_falls_back_to_ref_price_and_zero_fee():
    fill = market.create_order(_NoAvgExchange(), "BTC/USDT", "sell", 0.01, 63000.0, "T")
    assert fill.price == 63000.0 and fill.fee == 0.0   # ref_price fallback, fee defaults 0


class RecordingExchange:
    id = "binance"
    def __init__(self, exid="binance"):
        self.id = exid
        self.calls = []
    def create_order(self, symbol, otype, side, qty, price=None, params=None):
        self.calls.append({"symbol": symbol, "type": otype, "side": side,
                           "qty": qty, "price": price, "params": params})
        return {"status": "closed", "filled": qty, "average": price or 100.0,
                "fee": {"cost": 0.0}, "id": "1"}


def test_create_order_hyperliquid_passes_reference_price():
    ex = RecordingExchange("hyperliquid")
    fill = market.create_order(ex, "BTC/USDC", "buy", 0.5, 60000.0, "2026-07-01T00:00:00Z")
    assert ex.calls[0]["type"] == "market"
    assert ex.calls[0]["price"] == 60000.0     # HL needs the ref price to build its aggressive limit
    assert fill.qty == 0.5


def test_create_order_binance_sends_plain_market_no_price():
    ex = RecordingExchange("binance")
    market.create_order(ex, "BTC/USDT", "sell", 0.5, 60000.0, "2026-07-01T00:00:00Z")
    assert ex.calls[0]["type"] == "market"
    assert ex.calls[0]["price"] is None        # a true-market venue gets no price


class _LimitsExchange:
    markets = {"BTC/USDT": {"limits": {"amount": {"min": 0.001}, "cost": {"min": 10.0}}}}
    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"                       # 4-dp precision


def test_clamp_rounds_to_precision():
    assert market.clamp_to_market(_LimitsExchange(), "BTC/USDT", 0.0123456, 64000.0) == 0.0123


def test_clamp_below_min_amount_returns_zero():
    assert market.clamp_to_market(_LimitsExchange(), "BTC/USDT", 0.0005, 64000.0) == 0.0


def test_clamp_below_min_cost_returns_zero():
    # 0.0001 BTC * 64000 = 6.4 < 10.0 min cost
    assert market.clamp_to_market(_LimitsExchange(), "BTC/USDT", 0.0001, 64000.0) == 0.0


def test_clamp_unknown_market_passes_through():
    class _Bare:
        markets = {}
        def load_markets(self): return {}
    assert market.clamp_to_market(_Bare(), "BTC/USDT", 0.5, 100.0) == 0.5


class HLMarketExchange:
    id = "hyperliquid"
    markets = {"BTC/USDC": {"limits": {"amount": {"min": 0.001}, "cost": {"min": 10.0}},
                            "precision": {"amount": 0.0001}}}
    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"                     # 4-dp amount precision


def test_clamp_rounds_to_hl_amount_precision():
    ex = HLMarketExchange()
    assert market.clamp_to_market(ex, "BTC/USDC", 0.123456, 60000.0) == 0.1235


def test_clamp_zero_below_hl_min_amount():
    ex = HLMarketExchange()
    assert market.clamp_to_market(ex, "BTC/USDC", 0.0005, 60000.0) == 0.0   # below min amount 0.001


def test_clamp_zero_below_hl_min_cost():
    ex = HLMarketExchange()
    # 0.0002 BTC * 60000 = $12 > $10 min cost, OK; 0.0001 * 60000 = $6 < $10 -> 0
    assert market.clamp_to_market(ex, "BTC/USDC", 0.0001, 60000.0) == 0.0
