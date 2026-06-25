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
