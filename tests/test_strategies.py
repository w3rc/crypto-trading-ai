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
