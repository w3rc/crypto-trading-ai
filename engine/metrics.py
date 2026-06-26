def max_drawdown(curve):
    """Most negative peak-to-trough return over the curve (<= 0). e.g. -0.25."""
    if not curve:
        return 0.0
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        dd = v / peak - 1.0
        if dd < mdd:
            mdd = dd
    return mdd


def summarize(equity, buy_hold, n_trades):
    total_return = equity[-1] / equity[0] - 1.0
    buy_hold_return = buy_hold[-1] / buy_hold[0] - 1.0
    return {
        "final_equity": equity[-1],
        "total_return": total_return,
        "buy_hold_return": buy_hold_return,
        "max_drawdown": max_drawdown(equity),
        "n_trades": n_trades,
        "beats_hold": total_return > buy_hold_return,
    }
