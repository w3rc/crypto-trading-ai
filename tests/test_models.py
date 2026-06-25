import pytest
from pydantic import ValidationError
from engine.models import Decision, Position, Order, Fill

def test_decision_clamps_size():
    assert Decision(action="buy", size=5.0).size == 1.0
    assert Decision(action="buy", size=-2.0).size == 0.0

def test_decision_rejects_bad_action():
    with pytest.raises(ValidationError):
        Decision(action="moon")

def test_decision_ignores_extra_fields():
    d = Decision(action="hold", confidence=0.9)  # extra key ignored
    assert d.action == "hold"

def test_position_defaults_flat():
    p = Position(symbol="BTC/USDT")
    assert p.qty == 0.0 and p.avg_price == 0.0 and p.stop_price == 0.0
