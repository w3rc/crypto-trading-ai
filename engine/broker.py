from engine.models import Decision, Position, Order, Fill

_EPS = 1e-6


def plan_order(decision: Decision, position: Position, cash: float,
               price: float, equity: float, risk) -> Order | None:
    """Turn a decision into a clamped, executable order (or None).

    The gate is authoritative. Long-only by default; when risk.allow_short is
    true a sell opens/extends a short and a buy covers one. A reducing order
    clamps at flat (no single-order flip). |qty*price| never exceeds the cap.
    """
    if price <= 0:
        return None
    allow_short = bool(getattr(risk, "allow_short", False))   # None/False -> long-only
    qty = position.qty
    max_value = risk.max_position_pct * equity

    if decision.action == "buy":
        if qty < 0:                                   # cover a short -> clamp at flat
            q = min(decision.size * equity / price, -qty)
        else:                                         # open/extend long
            headroom = max(0.0, max_value - qty * price)
            q = min(decision.size * equity, headroom, cash) / price
        if q * price < _EPS:
            return None
        return Order(side="buy", qty=q, price=price)

    if decision.action == "sell":
        if qty > 0:                                   # reduce long -> clamp at flat
            q = min(decision.size * qty, qty)
        elif allow_short:                             # open/extend short
            short_headroom = max(0.0, max_value - (-qty) * price)
            q = min(decision.size * equity, short_headroom) / price
        else:
            return None                               # spot long-only
        if q * price < _EPS:
            return None
        return Order(side="sell", qty=q, price=price)

    return None


def stop_triggered(position: Position, price: float) -> bool:
    if position.stop_price <= 0:
        return False
    if position.qty > 0:
        return price <= position.stop_price          # long stop below entry
    if position.qty < 0:
        return price >= position.stop_price          # short stop above entry
    return False


def _stop_price(avg: float, qty: float, stop_loss_pct: float) -> float:
    return avg * (1 - stop_loss_pct) if qty > 0 else avg * (1 + stop_loss_pct)


def apply_fill(order: Order, position: Position, cash: float, fee_pct: float,
               slippage_pct: float, stop_loss_pct: float, ts: str):
    """Simulate a fill on a signed position: returns (new_position, new_cash, fill)."""
    eff = order.price * (1 + slippage_pct) if order.side == "buy" else order.price * (1 - slippage_pct)
    notional = order.qty * eff
    fee = notional * fee_pct
    if order.side == "buy":
        spend = notional + fee
        assert spend <= cash + _EPS, "buy exceeds cash (risk gate failed)"
        new_cash = cash - spend
        new_qty = position.qty + order.qty
    else:                                             # sell
        new_cash = cash + (notional - fee)
        new_qty = position.qty - order.qty

    old_qty = position.qty
    if abs(new_qty) <= _EPS:                          # closed to flat
        new_pos = Position(position.symbol, 0.0, 0.0, 0.0)
    elif old_qty == 0 or ((old_qty > 0) == (new_qty > 0) and abs(new_qty) > abs(old_qty)):
        # opening or extending the same direction -> weighted-average entry
        new_avg = (abs(old_qty) * position.avg_price + order.qty * eff) / abs(new_qty)
        new_pos = Position(position.symbol, new_qty, new_avg,
                           _stop_price(new_avg, new_qty, stop_loss_pct))
    elif (old_qty > 0) != (new_qty > 0):
        # crossed zero (flip) -> fresh position at the fill price
        new_pos = Position(position.symbol, new_qty, eff,
                           _stop_price(eff, new_qty, stop_loss_pct))
    else:
        # reduced toward flat (same direction) -> avg/stop unchanged
        new_pos = Position(position.symbol, new_qty, position.avg_price, position.stop_price)

    return new_pos, new_cash, Fill(position.symbol, order.side, order.qty, eff, fee, ts)
