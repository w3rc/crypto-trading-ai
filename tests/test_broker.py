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


def test_buy_then_sell_roundtrip_profit_minus_costs():
    from engine.broker import apply_fill
    pos = Position("BTC/USDT")
    from engine.models import Order
    pos2, cash2, fill_b = apply_fill(Order("buy", 1.0, 100.0), pos, 1000.0,
                                     fee_pct=0.001, slippage_pct=0.0005,
                                     stop_loss_pct=0.05, ts="t1")
    assert cash2 < 1000.0
    assert pos2.qty == pytest.approx(1.0)
    assert pos2.stop_price == pytest.approx(pos2.avg_price * 0.95)
    pos3, cash3, fill_s = apply_fill(Order("sell", 1.0, 110.0), pos2, cash2,
                                     fee_pct=0.001, slippage_pct=0.0005,
                                     stop_loss_pct=0.05, ts="t2")
    assert pos3.qty == 0.0 and pos3.avg_price == 0.0   # flat after full exit
    assert 1000.0 < cash3 < 1010.0                     # profit on +10 move, minus costs

def test_buy_exceeding_cash_asserts():
    from engine.broker import apply_fill
    from engine.models import Order
    with pytest.raises(AssertionError):
        apply_fill(Order("buy", 100.0, 100.0), Position("BTC/USDT"), 50.0,
                   0.001, 0.0005, 0.05, "t")

def test_sell_exceeding_holdings_asserts():
    from engine.broker import apply_fill
    from engine.models import Order
    with pytest.raises(AssertionError):
        apply_fill(Order("sell", 5.0, 100.0), Position("BTC/USDT", qty=1.0),
                   0.0, 0.001, 0.0005, 0.05, "t")

def test_buy_into_existing_position_weighted_avg_and_stop():
    from engine.broker import apply_fill
    from engine.models import Order
    pos = Position("BTC/USDT")
    pos2, cash2, _ = apply_fill(Order("buy", 1.0, 100.0), pos, 1000.0, 0.0, 0.0, 0.05, "t1")
    pos3, cash3, _ = apply_fill(Order("buy", 1.0, 120.0), pos2, cash2, 0.0, 0.0, 0.05, "t2")
    assert pos3.qty == pytest.approx(2.0)
    assert pos3.avg_price == pytest.approx(110.0)            # (100+120)/2
    assert pos3.stop_price == pytest.approx(110.0 * 0.95)    # stop recomputed off the new avg (intended v1 policy)

def test_partial_sell_preserves_avg_and_stop():
    from engine.broker import apply_fill
    from engine.models import Order
    pos = Position("BTC/USDT", qty=10.0, avg_price=100.0, stop_price=95.0)
    pos2, cash2, _ = apply_fill(Order("sell", 4.0, 110.0), pos, 0.0, 0.0, 0.0, 0.05, "t")
    assert pos2.qty == pytest.approx(6.0)
    assert pos2.avg_price == pytest.approx(100.0)   # cost basis unchanged on partial sell
    assert pos2.stop_price == pytest.approx(95.0)   # stop preserved on partial sell
    assert cash2 == pytest.approx(440.0)            # 4 * 110, no fees/slippage
