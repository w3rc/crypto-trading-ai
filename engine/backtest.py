from datetime import datetime, timezone

from engine import broker, datafeed, indicators, metrics, strategies
from engine.models import Order, Position


def _iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).isoformat()


def _common_timeline(data):
    sets = [set(df["ts"].tolist()) for df in data.values()]
    common = set.intersection(*sets) if sets else set()
    return sorted(common)


def _buy_hold_curve(price_history, symbols, cfg):
    curve = [cfg.paper_capital]
    if not price_history:
        return curve
    per = cfg.paper_capital / len(symbols)
    first = price_history[0]
    qty = {}
    for s in symbols:
        eff = first[s] * (1 + cfg.slippage_pct)   # same entry slippage as the strategy
        fee = per * cfg.fee_pct
        qty[s] = (per - fee) / eff
    for prices in price_history:
        curve.append(sum(qty[s] * prices[s] for s in symbols))
    return curve


def run_backtest(symbols, timeframe, since_ms, until_ms, strategy_name, cfg,
                 feed=datafeed.load_ohlcv, exchange=None, strategy=None):
    data = {sym: feed(exchange, sym, timeframe, since_ms, until_ms) for sym in symbols}
    timeline = _common_timeline(data)
    strat = strategy or strategies.get(strategy_name)

    cash = cfg.paper_capital
    positions = {sym: Position(sym) for sym in symbols}
    equity_curve = [cfg.paper_capital]
    price_history = []
    trades = []

    for ts in timeline:
        windows = {sym: data[sym][data[sym]["ts"] <= ts] for sym in symbols}
        if any(len(w) < indicators.MIN_ROWS for w in windows.values()):
            continue  # warmup: skip until every symbol has enough rows
        # ponytail: recomputes indicators over the whole trailing window each step
        # (O(n^2) total); precompute rolling indicators if backtests get slow.
        feats = {sym: indicators.compute_indicators(windows[sym]) for sym in symbols}
        prices = {sym: feats[sym]["price"] for sym in symbols}

        equity = cash + sum(positions[s].qty * prices[s] for s in symbols)
        for sym in symbols:
            pos = positions[sym]
            price = prices[sym]
            if broker.stop_triggered(pos, price):
                order = Order("sell", pos.qty, price)
            else:
                decision = strat(feats[sym], pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
            if order is not None:
                positions[sym], cash, fill = broker.apply_fill(
                    order, pos, cash, cfg.fee_pct, cfg.slippage_pct,
                    cfg.risk.stop_loss_pct, _iso(ts))
                trades.append(fill)

        price_history.append(prices)
        equity_curve.append(cash + sum(positions[s].qty * prices[s] for s in symbols))

    buy_hold_curve = _buy_hold_curve(price_history, symbols, cfg)
    summary = metrics.summarize(equity_curve, buy_hold_curve, len(trades))
    return {"metrics": summary, "equity_curve": equity_curve,
            "buy_hold_curve": buy_hold_curve, "trades": trades, "timeline": timeline}
