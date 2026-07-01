import pytest
from types import SimpleNamespace
from engine import strategies
from engine.models import Decision, Position


def test_get_returns_registered_callable():
    assert strategies.get("hybrid") is strategies.hybrid


def test_get_unknown_name_raises_listing_valid():
    with pytest.raises(ValueError) as e:
        strategies.get("nope")
    assert "hybrid" in str(e.value)


def test_hybrid_delegates_to_llm_with_llm_cfg(monkeypatch):
    captured = {}

    def fake_decide(features, position, cash, llm_cfg):
        captured["call"] = (features, position, cash, llm_cfg)
        return Decision(action="hold", reason="stub")

    monkeypatch.setattr(strategies.llm, "decide", fake_decide)
    cfg = SimpleNamespace(llm="LLM_CFG")
    d = strategies.hybrid({"price": 1.0}, Position("BTC/USDT"), 100.0, cfg)
    assert d.reason == "stub"
    assert captured["call"][3] == "LLM_CFG"   # forwards cfg.llm, not the whole cfg


def _ns(rsi_buy=30, rsi_sell=70, buy_size=0.5):
    return SimpleNamespace(rules=SimpleNamespace(
        rsi_buy=rsi_buy, rsi_sell=rsi_sell, buy_size=buy_size))


_FLAT = Position("BTC/USDT")


def _feats(rsi, macd=0.0, sig=0.0, fast=100.0, slow=100.0):
    return {"price": 100.0, "rsi": rsi, "macd": macd, "macd_signal": sig,
            "ma_fast": fast, "ma_slow": slow, "atr": 1.0}


def test_oversold_is_buy_with_buy_size():
    d = strategies.indicator_rule(_feats(rsi=25), _FLAT, 1000.0, _ns(buy_size=0.4))
    assert d.action == "buy" and d.size == 0.4


def test_overbought_is_sell_full():
    # emits sell holdings-agnostically; a sell-while-flat is gate-nullified downstream
    d = strategies.indicator_rule(_feats(rsi=80), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0


def test_macd_crossover_only_is_buy():
    # RSI neutral, but macd>signal AND ma_fast>ma_slow -> bullish via the OR's second leg
    d = strategies.indicator_rule(
        _feats(rsi=50, macd=1, sig=0, fast=101, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "buy"


def test_neutral_is_hold():
    d = strategies.indicator_rule(_feats(rsi=50), _FLAT, 1000.0, _ns())
    assert d.action == "hold"


def test_conflicting_signals_is_hold():
    # bullish via rsi<30 AND bearish via macd<signal & fast<slow -> hold
    d = strategies.indicator_rule(
        _feats(rsi=25, macd=-1, sig=0, fast=99, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "hold"


def test_indicator_rule_registered():
    assert strategies.get("indicator_rule") is strategies.indicator_rule


def _ns_s(rsi_buy=30, rsi_sell=70, buy_size=0.5, buy_min=-0.2, sell_max=-0.5):
    return SimpleNamespace(
        rules=SimpleNamespace(rsi_buy=rsi_buy, rsi_sell=rsi_sell, buy_size=buy_size),
        sentiment=SimpleNamespace(buy_min=buy_min, sell_max=sell_max))


def _feats_s(rsi, sentiment, macd=0.0, sig=0.0, fast=100.0, slow=100.0):
    return {"price": 100.0, "rsi": rsi, "macd": macd, "macd_signal": sig,
            "ma_fast": fast, "ma_slow": slow, "atr": 1.0, "sentiment": sentiment}


def test_sentiment_rule_bullish_confirmed_buys():
    d = strategies.sentiment_rule(_feats_s(rsi=25, sentiment=0.5), _FLAT, 1000.0, _ns_s())
    assert d.action == "buy" and d.size == 0.5


def test_sentiment_rule_bullish_vetoed_by_negative():
    d = strategies.sentiment_rule(_feats_s(rsi=25, sentiment=-0.5), _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"          # indicators bullish but sentiment < buy_min -> veto


def test_sentiment_rule_bearish_sells():
    d = strategies.sentiment_rule(_feats_s(rsi=80, sentiment=0.9), _FLAT, 1000.0, _ns_s())
    assert d.action == "sell" and d.size == 1.0


def test_sentiment_rule_neutral_extreme_negative_exits():
    d = strategies.sentiment_rule(_feats_s(rsi=50, sentiment=-0.6), _FLAT, 1000.0, _ns_s())
    assert d.action == "sell"          # neutral indicators, sentiment <= sell_max -> risk-off


def test_sentiment_rule_neutral_holds():
    d = strategies.sentiment_rule(_feats_s(rsi=50, sentiment=0.0), _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"


def test_sentiment_rule_conflict_holds():
    # bullish via rsi<30 AND bearish via macd<sig & fast<slow -> conflict -> hold (even if very negative)
    d = strategies.sentiment_rule(
        _feats_s(rsi=25, sentiment=-0.9, macd=-1, sig=0, fast=99, slow=100),
        _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"


def test_sentiment_rule_missing_key_treated_as_neutral():
    feats = {"price": 100.0, "rsi": 50, "macd": 0.0, "macd_signal": 0.0,
             "ma_fast": 100.0, "ma_slow": 100.0, "atr": 1.0}   # no "sentiment"
    d = strategies.sentiment_rule(feats, _FLAT, 1000.0, _ns_s())
    assert d.action == "hold"          # sentiment defaults to 0.0 -> neutral hold


def test_sentiment_rule_registered():
    assert strategies.get("sentiment_rule") is strategies.sentiment_rule


def _feats_bb(price, lower, upper):
    return {"price": price, "bb_lower": lower, "bb_upper": upper,
            "rsi": 50, "macd": 0.0, "macd_signal": 0.0,
            "ma_fast": 100.0, "ma_slow": 100.0, "atr": 1.0}


def test_ma_cross_golden_buys():
    d = strategies.ma_cross(_feats(rsi=50, fast=101, slow=100), _FLAT, 1000.0, _ns(buy_size=0.4))
    assert d.action == "buy" and d.size == 0.4

def test_ma_cross_death_sells():
    d = strategies.ma_cross(_feats(rsi=50, fast=99, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_ma_cross_equal_holds():
    d = strategies.ma_cross(_feats(rsi=50, fast=100, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_macd_cross_bull_buys():
    d = strategies.macd_cross(_feats(rsi=50, macd=1, sig=0), _FLAT, 1000.0, _ns(buy_size=0.5))
    assert d.action == "buy" and d.size == 0.5

def test_macd_cross_bear_sells():
    d = strategies.macd_cross(_feats(rsi=50, macd=-1, sig=0), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_macd_cross_equal_holds():
    d = strategies.macd_cross(_feats(rsi=50, macd=0, sig=0), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_rsi_reversion_oversold_buys():
    d = strategies.rsi_reversion(_feats(rsi=25), _FLAT, 1000.0, _ns(buy_size=0.3))
    assert d.action == "buy" and d.size == 0.3

def test_rsi_reversion_overbought_sells():
    d = strategies.rsi_reversion(_feats(rsi=80), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_rsi_reversion_neutral_holds():
    d = strategies.rsi_reversion(_feats(rsi=50), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_bollinger_below_lower_buys():
    d = strategies.bollinger(_feats_bb(price=90, lower=95, upper=105), _FLAT, 1000.0, _ns(buy_size=0.6))
    assert d.action == "buy" and d.size == 0.6

def test_bollinger_above_upper_sells():
    d = strategies.bollinger(_feats_bb(price=110, lower=95, upper=105), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_bollinger_inside_holds():
    d = strategies.bollinger(_feats_bb(price=100, lower=95, upper=105), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_new_presets_registered():
    for name in ("ma_cross", "macd_cross", "rsi_reversion", "bollinger"):
        assert strategies.get(name) is getattr(strategies, name)
