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
    return position.qty > 0 and position.stop_price > 0 and price <= position.stop_price


def apply_fill(order: Order, position: Position, cash: float, fee_pct: float,
               slippage_pct: float, stop_loss_pct: float, ts: str):
    """Simulate a fill: returns (new_position, new_cash, fill_record)."""
    if order.side == "buy":
        eff = order.price * (1 + slippage_pct)
        notional = order.qty * eff
        fee = notional * fee_pct
        spend = notional + fee
        assert spend <= cash + _EPS, "buy exceeds cash (risk gate failed)"
        new_qty = position.qty + order.qty
        new_avg = (position.qty * position.avg_price + order.qty * eff) / new_qty
        new_pos = Position(position.symbol, new_qty, new_avg, new_avg * (1 - stop_loss_pct))
        return new_pos, cash - spend, Fill(position.symbol, "buy", order.qty, eff, fee, ts)

    # sell
    assert order.qty <= position.qty + _EPS, "sell exceeds holdings (risk gate failed)"
    eff = order.price * (1 - slippage_pct)
    notional = order.qty * eff
    fee = notional * fee_pct
    new_qty = position.qty - order.qty
    if new_qty <= _EPS:
        new_pos = Position(position.symbol, 0.0, 0.0, 0.0)
    else:
        new_pos = Position(position.symbol, new_qty, position.avg_price, position.stop_price)
    return new_pos, cash + (notional - fee), Fill(position.symbol, "sell", order.qty, eff, fee, ts)
