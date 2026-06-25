from engine.models import Decision, Position, Order, Fill

_EPS = 1e-6


def plan_order(decision: Decision, position: Position, cash: float,
               price: float, equity: float, risk) -> Order | None:
    """Turn an LLM decision into a clamped, executable order (or None).

    The gate is authoritative: buys are capped to the per-position limit AND
    available cash; sells are capped to held quantity. Spot long-only, so a
    sell never exceeds holdings and a buy never exceeds the cap.
    """
    if price <= 0:
        return None
    if decision.action == "buy":
        max_position_value = risk.max_position_pct * equity
        headroom = max(0.0, max_position_value - position.qty * price)
        notional = min(decision.size * equity, headroom, cash)
        qty = notional / price
        if qty * price < _EPS:
            return None
        return Order(side="buy", qty=qty, price=price)
    if decision.action == "sell":
        qty = min(decision.size * position.qty, position.qty)
        if qty <= _EPS:
            return None
        return Order(side="sell", qty=qty, price=price)
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
