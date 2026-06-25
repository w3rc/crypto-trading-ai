from engine.models import Decision, Position, Order

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
