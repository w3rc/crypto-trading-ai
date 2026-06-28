import pytest
from engine.models import Decision, Position
from engine.config import RiskConfig
from engine.broker import plan_order, stop_triggered

RISK = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05)
RISK_LEV = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05, leverage=5.0,
                      maintenance_margin_pct=0.005)

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

def test_buy_clamped_to_cash_no_crash():
    from engine.broker import apply_fill
    from engine.models import Order
    # buying 100 @ 100 with only 50 cash: fills only what cash affords, never asserts
    pos2, cash2, fill = apply_fill(Order("buy", 100.0, 100.0), Position("BTC/USDT"), 50.0,
                                   0.001, 0.0005, 0.05, "t")
    assert fill.qty < 100.0                  # partial fill, clamped
    assert cash2 >= -1e-6                     # never overspent
    assert pos2.qty == pytest.approx(fill.qty)

def test_sell_beyond_long_clamps_at_flat():
    from engine.broker import apply_fill
    from engine.models import Order
    # a sell larger than the long reduces to flat (no single-order flip; gate forbids it)
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0)
    pos2, _, fill = apply_fill(Order("sell", 5.0, 100.0), pos, 0.0, 0.0, 0.0, 0.05, "t")
    assert pos2.qty == 0.0                             # closed to flat, not flipped
    assert fill.qty == pytest.approx(1.0)              # only the 1 unit to flat filled


def test_open_short_sets_negative_qty_and_stop_above():
    from engine.broker import apply_fill
    from engine.models import Order
    pos2, cash2, _ = apply_fill(Order("sell", 2.0, 100.0), Position("BTC/USDT"), 1000.0,
                                0.0, 0.0, 0.05, "t")
    assert pos2.qty == pytest.approx(-2.0)
    assert pos2.avg_price == pytest.approx(100.0)
    assert pos2.stop_price == pytest.approx(105.0)     # 100*(1+0.05)
    assert cash2 == pytest.approx(800.0)               # isolated margin: 1000 - 200 locked


def test_extend_short_weighted_avg():
    from engine.broker import apply_fill
    from engine.models import Order
    pos = Position("BTC/USDT", qty=-2.0, avg_price=100.0, stop_price=105.0)
    pos2, _, _ = apply_fill(Order("sell", 1.0, 130.0), pos, 1000.0, 0.0, 0.0, 0.05, "t")
    assert pos2.qty == pytest.approx(-3.0)
    assert pos2.avg_price == pytest.approx((2 * 100 + 1 * 130) / 3)   # 110


def test_cover_partial_preserves_avg():
    from engine.broker import apply_fill
    from engine.models import Order
    pos = Position("BTC/USDT", qty=-10.0, avg_price=100.0, stop_price=105.0)
    pos2, cash2, _ = apply_fill(Order("buy", 4.0, 90.0), pos, 2000.0, 0.0, 0.0, 0.05, "t")
    assert pos2.qty == pytest.approx(-6.0)
    assert pos2.avg_price == pytest.approx(100.0)      # cost basis unchanged on partial cover
    assert pos2.stop_price == pytest.approx(105.0)


def test_short_profit_when_price_falls():
    from engine.broker import apply_fill
    from engine.models import Order
    # open short at 100, cover at 90 -> profit
    pos2, cash2, _ = apply_fill(Order("sell", 1.0, 100.0), Position("BTC/USDT"), 1000.0, 0.0, 0.0, 0.05, "t")
    pos3, cash3, _ = apply_fill(Order("buy", 1.0, 90.0), pos2, cash2, 0.0, 0.0, 0.05, "t2")
    assert pos3.qty == 0.0                              # flat
    assert cash3 == pytest.approx(1010.0)              # +100 -90 = +10 profit


def test_short_stop_fires_above_entry():
    pos = Position("BTC/USDT", qty=-1.0, avg_price=100.0, stop_price=105.0)
    assert stop_triggered(pos, 106) is True            # price rose past the short stop
    assert stop_triggered(pos, 104) is False

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


RISK_S = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05, allow_short=True)


def test_buy_cap_scales_with_leverage():
    # equity 1000, cap 0.25 -> 250 at 1x; 5x lifts the cap to 1250 notional / 10 = 125
    risk = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05, leverage=5.0)
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=10000, price=10, equity=1000, risk=risk)
    assert o.qty == pytest.approx(125.0)

def test_buy_open_bounded_by_cash_times_leverage():
    # only 100 cash, 5x -> can open up to 100*5=500 notional / 10 = 50 (margin-bounded)
    risk = RiskConfig(max_position_pct=1.0, stop_loss_pct=0.05, leverage=5.0)
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=100, price=10, equity=1_000_000, risk=risk)
    assert o.qty == pytest.approx(50.0)

def test_short_open_bounded_by_cash_times_leverage():
    # short open now needs margin: 100 cash, 5x -> 500 notional / 10 = 50
    risk = RiskConfig(max_position_pct=1.0, stop_loss_pct=0.05, leverage=5.0, allow_short=True)
    o = plan_order(Decision(action="sell", size=1.0),
                   Position("BTC/USDT"), cash=100, price=10, equity=1_000_000, risk=risk)
    assert o.side == "sell" and o.qty == pytest.approx(50.0)

def test_sell_when_flat_opens_short_capped():
    # equity 1000 -> cap 250; sell from flat opens a short up to the cap (needs margin now)
    o = plan_order(Decision(action="sell", size=1.0),
                   Position("BTC/USDT"), cash=10000, price=10, equity=1000, risk=RISK_S)
    assert o.side == "sell" and o.qty == pytest.approx(25.0)   # 250 notional / 10


def test_sell_extends_short_up_to_cap():
    pos = Position("BTC/USDT", qty=-10, avg_price=10, stop_price=10.5)  # short notional 100
    o = plan_order(Decision(action="sell", size=1.0), pos, cash=10000, price=10, equity=1000, risk=RISK_S)
    assert o.qty == pytest.approx(15.0)    # remaining short headroom 250-100=150 / 10


def test_buy_covers_short_clamped_at_flat():
    pos = Position("BTC/USDT", qty=-10, avg_price=10, stop_price=10.5)
    o = plan_order(Decision(action="buy", size=1.0), pos, cash=10000, price=10, equity=1000, risk=RISK_S)
    assert o.side == "buy" and o.qty == pytest.approx(10.0)   # covers exactly to flat, no flip


def test_buy_partial_cover_short():
    pos = Position("BTC/USDT", qty=-10, avg_price=10, stop_price=10.5)
    o = plan_order(Decision(action="buy", size=0.05), pos, cash=10000, price=10, equity=1000, risk=RISK_S)
    assert o.qty == pytest.approx(5.0)     # 0.05*1000/10 = 5, below the 10 to flat


def test_sell_when_flat_is_none_without_allow_short():
    # the existing long-only behavior still holds when allow_short is off (default None)
    assert plan_order(Decision(action="sell", size=1.0),
                      Position("BTC/USDT"), cash=0, price=10, equity=1000, risk=RISK) is None



def test_open_long_locks_margin_not_full_notional():
    from engine.broker import apply_fill
    from engine.models import Order
    # 5x: opening 5 @ 100 (notional 500) locks only 500/5 = 100 of cash
    pos2, cash2, _ = apply_fill(Order("buy", 5.0, 100.0), Position("BTC/USDT"), 1000.0,
                                0.0, 0.0, 0.05, "t", leverage=5.0)
    assert pos2.qty == pytest.approx(5.0)
    assert pos2.avg_price == pytest.approx(100.0)
    assert pos2.leverage == 5.0
    assert cash2 == pytest.approx(900.0)          # 1000 - 100 margin (not 500)

def test_leveraged_long_roundtrip_pnl_matches_unleveraged():
    from engine.broker import apply_fill
    from engine.models import Order
    # leverage changes margin, not absolute P&L: +10 move on 1 unit = +10 either way
    pos2, cash2, _ = apply_fill(Order("buy", 1.0, 100.0), Position("BTC/USDT"), 1000.0,
                                0.0, 0.0, 0.05, "t", leverage=5.0)
    pos3, cash3, _ = apply_fill(Order("sell", 1.0, 110.0), pos2, cash2,
                                0.0, 0.0, 0.05, "t2", leverage=5.0)
    assert pos3.qty == 0.0
    assert cash3 == pytest.approx(1010.0)         # +10 profit, same as 1x

def test_bad_debt_cover_clamps_cash_to_zero_no_crash():
    from engine.broker import apply_fill
    from engine.models import Order
    # underwater short, price gapped far past liquidation: cover realizes a loss
    # bigger than released margin -> cash clamps to 0 (bad debt), never negative/crash
    pos = Position("BTC/USDT", qty=-1.0, avg_price=100.0, stop_price=105.0)
    pos2, cash2, fill = apply_fill(Order("buy", 1.0, 250.0), pos, 10.0, 0.0, 0.0, 0.05, "t")
    assert fill.qty == pytest.approx(1.0)         # fully covers (margin released)
    assert pos2.qty == 0.0
    assert cash2 == 0.0                            # bad-debt clamp, no crash


def test_liquidation_price_long():
    from engine.broker import liquidation_price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert liquidation_price(pos, 0.005) == pytest.approx(100 * (1 - 1/5) / (1 - 0.005))

def test_liquidation_price_short():
    from engine.broker import liquidation_price
    pos = Position("BTC/USDT", qty=-1.0, avg_price=100.0, stop_price=105.0, leverage=5.0)
    assert liquidation_price(pos, 0.005) == pytest.approx(100 * (1 + 1/5) / (1 + 0.005))

def test_liquidation_price_unleveraged_is_zero():
    from engine.broker import liquidation_price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=1.0)
    assert liquidation_price(pos, 0.005) == 0.0

def test_liquidation_price_flat_is_zero():
    from engine.broker import liquidation_price
    assert liquidation_price(Position("BTC/USDT", leverage=5.0), 0.005) == 0.0

def test_force_close_liquidation_outranks_stop():
    from engine.broker import force_close
    # 5x long, avg 100 -> liq ~80.4; price 80 is below BOTH the 95 stop and the liq price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert force_close(pos, 80.0, RISK_LEV) == "liquidation"

def test_force_close_stop_when_only_stop_hit():
    from engine.broker import force_close
    # price 90 is below the 95 stop but above the ~80.4 liq price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert force_close(pos, 90.0, RISK_LEV) == "stop-loss"

def test_force_close_none_when_safe():
    from engine.broker import force_close
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert force_close(pos, 120.0, RISK_LEV) is None

def test_force_close_liquidation_short():
    from engine.broker import force_close
    # 5x short, avg 100 -> liq ~119.4; price 120 is above the liq price
    pos = Position("BTC/USDT", qty=-1.0, avg_price=100.0, stop_price=105.0, leverage=5.0)
    assert force_close(pos, 120.0, RISK_LEV) == "liquidation"

def test_force_close_unleveraged_never_liquidates():
    from engine.broker import force_close
    RISK_SPOT = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05)
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=1.0)
    # price 50 is below the stop but must NOT return "liquidation"
    assert force_close(pos, 50.0, RISK_SPOT) == "stop-loss"

def test_force_close_risk_without_mmr_attr_uses_default():
    from engine.broker import force_close
    class _R:  # a risk object lacking maintenance_margin_pct -> getattr default 0.005
        pass
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    # liq ~80.4 with the default mmr; price 80 is below it -> liquidation, no AttributeError
    assert force_close(pos, 80.0, _R()) == "liquidation"


def test_funding_payment_long_pays_on_positive_rate():
    from engine.broker import funding_payment
    pos = Position("BTC/USDT", qty=2.0, avg_price=100.0)
    assert funding_payment(pos, 110.0, 0.001) == pytest.approx(-0.22)   # 0.001*2*110, long pays

def test_funding_payment_short_receives_on_positive_rate():
    from engine.broker import funding_payment
    pos = Position("BTC/USDT", qty=-2.0, avg_price=100.0)
    assert funding_payment(pos, 110.0, 0.001) == pytest.approx(0.22)    # short receives

def test_funding_payment_negative_rate_flips():
    from engine.broker import funding_payment
    pos = Position("BTC/USDT", qty=2.0, avg_price=100.0)
    assert funding_payment(pos, 110.0, -0.001) == pytest.approx(0.22)   # long receives on -rate

def test_funding_payment_flat_is_zero():
    from engine.broker import funding_payment
    assert funding_payment(Position("BTC/USDT"), 110.0, 0.001) == 0.0

def test_funding_due_boundary():
    from engine.broker import funding_due
    h = 3_600_000
    assert funding_due(0, 8 * h - 1, 8) is False     # just under the 8h interval
    assert funding_due(0, 8 * h, 8) is True          # exactly at the boundary
    assert funding_due(0, 9 * h, 8) is True
    assert funding_due(None, 8 * h, 8) is False      # no prior funding -> never due
