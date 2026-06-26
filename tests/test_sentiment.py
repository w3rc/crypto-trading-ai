from types import SimpleNamespace
import pytest
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


def test_cryptopanic_vote_ratio(monkeypatch):
    monkeypatch.setenv("CRYPTOPANIC_TOKEN", "tok")
    payload = {"results": [
        {"votes": {"positive": 6, "negative": 2}},
        {"votes": {"positive": 0, "negative": 0}},
    ]}
    monkeypatch.setattr(sentiment, "_http_json", lambda *a, **k: payload)
    out = sentiment.cryptopanic(["BTC/USDT"], _cfg())
    assert out["BTC/USDT"] == (6 - 2) / (6 + 2)   # 0.5


def test_cryptopanic_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("CRYPTOPANIC_TOKEN", raising=False)
    assert sentiment.cryptopanic(["BTC/USDT"], _cfg()) == {}


def test_cryptopanic_backtest_returns_empty(monkeypatch):
    monkeypatch.setenv("CRYPTOPANIC_TOKEN", "tok")
    assert sentiment.cryptopanic(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1) == {}


def test_reddit_scores_titles_with_vader(monkeypatch):
    monkeypatch.setattr(sentiment, "_reddit_token", lambda cfg: "tok")
    payload = {"data": {"children": [
        {"data": {"title": "bullish breakout, mooning"}},
        {"data": {"title": "great accumulation zone, very bullish"}},
    ]}}
    monkeypatch.setattr(sentiment, "_http_json", lambda *a, **k: payload)
    out = sentiment.reddit(["BTC/USDT"], _cfg())
    assert out["BTC/USDT"] > 0


def test_reddit_no_token_returns_empty(monkeypatch):
    monkeypatch.setattr(sentiment, "_reddit_token", lambda cfg: None)
    assert sentiment.reddit(["BTC/USDT"], _cfg()) == {}


def test_x_twitter_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    assert sentiment.x_twitter(["BTC/USDT"], _cfg()) == {}


def test_x_twitter_scores_tweets(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "tok")
    payload = {"data": [{"text": "bearish, dumping, rug"}, {"text": "scam, crashing"}]}
    monkeypatch.setattr(sentiment, "_http_json", lambda *a, **k: payload)
    assert sentiment.x_twitter(["BTC/USDT"], _cfg())["BTC/USDT"] < 0


def test_sources_registry_has_four():
    assert set(sentiment.SOURCES) == {"fear_greed", "cryptopanic", "reddit", "x_twitter"}


@pytest.fixture(autouse=True)
def _clear_cache():
    sentiment._CACHE.clear()
    yield
    sentiment._CACHE.clear()


def test_aggregate_weighted_blend(monkeypatch):
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 1.0 for x in s})
    monkeypatch.setitem(sentiment.SOURCES, "cryptopanic",
                        lambda s, c, backtest=False, ts_ms=None: {x: -1.0 for x in s})
    monkeypatch.setitem(sentiment.SOURCES, "reddit",
                        lambda s, c, backtest=False, ts_ms=None: {})
    monkeypatch.setitem(sentiment.SOURCES, "x_twitter",
                        lambda s, c, backtest=False, ts_ms=None: {})
    cfg = _cfg(weights={"fear_greed": 3.0, "cryptopanic": 1.0,
                        "reddit": 1.0, "x_twitter": 1.0})
    out = sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    assert out["BTC/USDT"] == pytest.approx((3 * 1.0 + 1 * -1.0) / 4)   # 0.5


def test_aggregate_excluded_source_does_not_drag(monkeypatch):
    # only fear_greed reports; an absent source must NOT pull the score toward 0
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 0.8 for x in s})
    for name in ("cryptopanic", "reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    out = sentiment.aggregate_sentiment(["BTC/USDT"], _cfg())
    assert out["BTC/USDT"] == pytest.approx(0.8)


def test_aggregate_all_absent_is_zero(monkeypatch):
    for name in sentiment.SOURCES:
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    assert sentiment.aggregate_sentiment(["BTC/USDT"], _cfg())["BTC/USDT"] == 0.0


def test_aggregate_backtest_only_runs_fear_greed(monkeypatch):
    seen = []

    def fg(s, c, backtest=False, ts_ms=None):
        seen.append(("fear_greed", backtest))
        return {x: 0.5 for x in s}

    def others(s, c, backtest=False, ts_ms=None):
        seen.append(("other", backtest))
        return {}                          # adapters self-disable when backtest=True

    monkeypatch.setitem(sentiment.SOURCES, "fear_greed", fg)
    for name in ("cryptopanic", "reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name, others)
    out = sentiment.aggregate_sentiment(["BTC/USDT"], _cfg(), backtest=True, ts_ms=1)
    assert out["BTC/USDT"] == 0.5
    assert ("fear_greed", True) in seen      # fear_greed called in backtest mode


def test_aggregate_caches_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake(s, c, backtest=False, ts_ms=None):
        calls["n"] += 1
        return {x: 0.4 for x in s}

    monkeypatch.setitem(sentiment.SOURCES, "fear_greed", fake)
    cfg = _cfg(weights={"fear_greed": 1.0})   # only fear_greed weighted
    sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    assert calls["n"] == 1                     # second call served from cache


def test_aggregate_survives_a_raising_source(monkeypatch):
    def boom(symbols, cfg, backtest=False, ts_ms=None):
        raise RuntimeError("source exploded")
    monkeypatch.setitem(sentiment.SOURCES, "cryptopanic", boom)
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 0.6 for x in s})
    for name in ("reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    out = sentiment.aggregate_sentiment(["BTC/USDT"], _cfg())   # must NOT raise
    assert out["BTC/USDT"] == pytest.approx(0.6)                # the good source still counts
