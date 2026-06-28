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
    lev = max(1.0, getattr(risk, "leverage", 1.0))
    qty = position.qty
    max_value = risk.max_position_pct * equity * lev          # leverage scales the cap

    if decision.action == "buy":
        if qty < 0:                                   # cover a short -> clamp at flat
            q = min(decision.size * equity * lev / price, -qty)
        else:                                         # open/extend long
            headroom = max(0.0, max_value - qty * price)
            q = min(decision.size * equity * lev, headroom, cash * lev) / price
        if q * price < _EPS:
            return None
        return Order(side="buy", qty=q, price=price)

    if decision.action == "sell":
        if qty > 0:                                   # reduce long -> clamp at flat
            q = min(decision.size * qty, qty)
        elif allow_short:                             # open/extend short (needs margin)
            short_headroom = max(0.0, max_value - (-qty) * price)
            q = min(decision.size * equity * lev, short_headroom, cash * lev) / price
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


def liquidation_price(position: Position, maintenance_margin_pct: float) -> float:
    """Isolated-margin liquidation price; 0.0 means 'never' (unleveraged/flat)."""
    L = position.leverage
    avg = position.avg_price
    if L <= 1.0 or avg <= 0 or abs(position.qty) <= _EPS:
        return 0.0
    mmr = maintenance_margin_pct
    if position.qty > 0:
        return avg * (1 - 1.0 / L) / (1 - mmr)
    return avg * (1 + 1.0 / L) / (1 + mmr)


def force_close(position: Position, price: float, risk) -> str | None:
    """Why the position must be force-closed this cycle, if at all.

    Liquidation outranks the protective stop. Returns "liquidation",
    "stop-loss", or None.
    """
    liq = liquidation_price(position, getattr(risk, "maintenance_margin_pct", 0.005))
    if liq > 0:
        if position.qty > 0 and price <= liq:
            return "liquidation"
        if position.qty < 0 and price >= liq:
            return "liquidation"
    if stop_triggered(position, price):
        return "stop-loss"
    return None


def _stop_price(avg: float, qty: float, stop_loss_pct: float) -> float:
    return avg * (1 - stop_loss_pct) if qty > 0 else avg * (1 + stop_loss_pct)


def apply_fill(order: Order, position: Position, cash: float, fee_pct: float,
               slippage_pct: float, stop_loss_pct: float, ts: str):
    """Simulate a fill on a signed position: returns (new_position, new_cash, fill)."""
    if order.side == "buy":
        eff = order.price * (1 + slippage_pct)
        # ponytail: a long buy is cash-clamped by the gate; a cover / stop-close buy
        # is NOT (no leverage model yet), so clamp here -> a forced PARTIAL cover
        # instead of overspending or crashing. Full forced-close is liquidation (slice 2).
        affordable = cash / (eff * (1 + fee_pct)) if eff > 0 else 0.0
        filled = min(order.qty, max(0.0, affordable))
        notional = filled * eff
        fee = notional * fee_pct
        new_cash = cash - (notional + fee)
        new_qty = position.qty + filled
    else:                                             # sell
        eff = order.price * (1 - slippage_pct)
        filled = order.qty
        notional = filled * eff
        fee = notional * fee_pct
        new_cash = cash + (notional - fee)
        new_qty = position.qty - filled

    old_qty = position.qty
    if abs(new_qty) <= _EPS:                          # closed to flat
        new_pos = Position(position.symbol, 0.0, 0.0, 0.0)
    elif old_qty == 0 or ((old_qty > 0) == (new_qty > 0) and abs(new_qty) > abs(old_qty)):
        new_avg = (abs(old_qty) * position.avg_price + filled * eff) / abs(new_qty)
        new_pos = Position(position.symbol, new_qty, new_avg,
                           _stop_price(new_avg, new_qty, stop_loss_pct))
    elif (old_qty > 0) != (new_qty > 0):              # crossed zero (flip)
        new_pos = Position(position.symbol, new_qty, eff,
                           _stop_price(eff, new_qty, stop_loss_pct))
    else:                                             # reduced toward flat
        new_pos = Position(position.symbol, new_qty, position.avg_price, position.stop_price)

    return new_pos, new_cash, Fill(position.symbol, order.side, filled, eff, fee, ts)
