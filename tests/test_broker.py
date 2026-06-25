import pytest
from engine.models import Decision, Position
from engine.config import RiskConfig
from engine.broker import plan_order, stop_triggered

RISK = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05)

def test_buy_capped_by_max_position_pct():
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=10000, price=10, equity=1000, risk=RISK)
    assert o.side == "buy"
    assert o.qty == pytest.approx(25.0)   # 0.25*1000=250 notional / 10

def test_buy_capped_by_cash():
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=100, price=10, equity=1_000_000, risk=RISK)
    assert o.qty == pytest.approx(10.0)   # cash 100 / price 10

def test_buy_respects_existing_position_value():
    pos = Position("BTC/USDT", qty=20, avg_price=10, stop_price=9)
    # equity 1000 -> max position value 250; already holding 20*10=200 -> only 50 headroom
    o = plan_order(Decision(action="buy", size=1.0), pos, cash=10000, price=10, equity=1000, risk=RISK)
    assert o.qty == pytest.approx(5.0)

def test_sell_capped_to_holdings():
    pos = Position("BTC/USDT", qty=4, avg_price=10, stop_price=9)
    o = plan_order(Decision(action="sell", size=1.0), pos, cash=0, price=10, equity=40, risk=RISK)
    assert o.side == "sell" and o.qty == pytest.approx(4.0)

def test_sell_when_flat_is_none():
    assert plan_order(Decision(action="sell", size=1.0),
                      Position("BTC/USDT"), cash=0, price=10, equity=0, risk=RISK) is None

def test_hold_is_none():
    assert plan_order(Decision(action="hold"),
                      Position("BTC/USDT"), cash=100, price=10, equity=100, risk=RISK) is None

def test_stop_triggered():
    pos = Position("BTC/USDT", qty=1, avg_price=100, stop_price=95)
    assert stop_triggered(pos, 94) is True
    assert stop_triggered(pos, 96) is False
    assert stop_triggered(Position("BTC/USDT"), 1) is False  # flat
