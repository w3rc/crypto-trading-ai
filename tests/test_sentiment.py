from types import SimpleNamespace
from engine import sentiment


def _cfg(weights=None):
    return SimpleNamespace(sentiment=SimpleNamespace(
        weights=weights or {"fear_greed": 1.0, "cryptopanic": 1.0,
                            "reddit": 1.0, "x_twitter": 1.0},
        cache_ttl={"fear_greed": 86400, "cryptopanic": 3600,
                   "reddit": 3600, "x_twitter": 3600},
        http_timeout=6.0, enabled=True, buy_min=-0.2, sell_max=-0.5))


def test_coin_extracts_base():
    assert sentiment._coin("BTC/USDT") == "BTC"
    assert sentiment._coin("eth/usdt") == "ETH"


def test_vader_score_sign_and_empty():
    assert sentiment._vader_score(["to the moon, super bullish breakout!"]) > 0
    assert sentiment._vader_score(["rug pull, scam, dumping hard, bearish"]) < 0
    assert sentiment._vader_score([]) is None


def test_fear_greed_normalizes_live(monkeypatch):
    monkeypatch.setattr(sentiment, "_http_json",
                        lambda *a, **k: {"data": [{"value": "75"}]})
    out = sentiment.fear_greed(["BTC/USDT", "ETH/USDT"], _cfg())
    assert out["BTC/USDT"] == 0.5 and out["ETH/USDT"] == 0.5   # (75-50)/50, market-wide


def test_fear_greed_extremes(monkeypatch):
    monkeypatch.setattr(sentiment, "_http_json",
                        lambda *a, **k: {"data": [{"value": "0"}]})
    assert sentiment.fear_greed(["BTC/USDT"], _cfg())["BTC/USDT"] == -1.0
    monkeypatch.setattr(sentiment, "_http_json",
                        lambda *a, **k: {"data": [{"value": "100"}]})
    assert sentiment.fear_greed(["BTC/USDT"], _cfg())["BTC/USDT"] == 1.0


def test_fear_greed_error_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(sentiment, "_http_json", boom)
    assert sentiment.fear_greed(["BTC/USDT"], _cfg()) == {}


def test_fear_greed_backtest_uses_history(monkeypatch):
    day = (1_700_000_000_000 // 86_400_000) * 86_400_000
    monkeypatch.setattr(sentiment, "_fng_history", lambda cfg: {day: 75.0})
    out = sentiment.fear_greed(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1_700_000_000_000)
    assert out["BTC/USDT"] == 0.5
    # a day with no history (and none in the prior week) -> empty
    monkeypatch.setattr(sentiment, "_fng_history", lambda cfg: {})
    assert sentiment.fear_greed(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1_700_000_000_000) == {}


def test_fng_lookup_floors_to_earlier_day():
    day = 10 * 86_400_000
    hist = {day - 2 * 86_400_000: 40.0}        # value 2 days earlier
    assert sentiment._fng_lookup(hist, day) == 40.0   # walks back to the nearest earlier day
    assert sentiment._fng_lookup({}, day) is None
