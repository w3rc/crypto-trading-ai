import argparse
import time
from datetime import datetime, timezone

from engine import broker, datafeed, indicators, market, metrics, sentiment, state, strategies
from engine.config import load_config
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
    if cfg.risk.allow_short is None and exchange is not None:
        cfg.risk.allow_short = market.supports_short(exchange)

    cash = cfg.paper_capital
    positions = {sym: Position(sym) for sym in symbols}
    equity_curve = [cfg.paper_capital]
    price_history = []
    trades = []
    last_funding_ms = None

    for ts in timeline:
        windows = {sym: data[sym][data[sym]["ts"] <= ts] for sym in symbols}
        if any(len(w) < indicators.MIN_ROWS for w in windows.values()):
            continue  # warmup: skip until every symbol has enough rows
        # ponytail: recomputes indicators over the whole trailing window each step
        # (O(n^2) total); precompute rolling indicators if backtests get slow.
        feats = {sym: indicators.compute_indicators(windows[sym]) for sym in symbols}
        prices = {sym: feats[sym]["price"] for sym in symbols}
        sent = (sentiment.aggregate_sentiment(symbols, cfg, backtest=True, ts_ms=ts)
                if cfg.sentiment.enabled else {})
        for sym in symbols:
            feats[sym]["sentiment"] = sent.get(sym, 0.0)
            feats[sym]["allow_short"] = bool(cfg.risk.allow_short)

        funding_due = cfg.risk.funding_rate != 0 and broker.funding_due(
            last_funding_ms, ts, cfg.risk.funding_interval_hours)
        if funding_due:
            for s in symbols:
                if positions[s].qty != 0:
                    cash = max(0.0, cash + broker.funding_payment(
                        positions[s], prices[s], cfg.risk.funding_rate))
        if cfg.risk.funding_rate != 0 and (last_funding_ms is None or funding_due):
            last_funding_ms = ts

        equity = cash + sum(state.position_value(positions[s], prices[s]) for s in symbols)
        for sym in symbols:
            pos = positions[sym]
            price = prices[sym]
            reason = broker.force_close(pos, price, cfg.risk)
            if reason:
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strat(feats[sym], pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
            if order is not None:
                positions[sym], cash, fill = broker.apply_fill(
                    order, pos, cash, cfg.fee_pct, cfg.slippage_pct,
                    cfg.risk.stop_loss_pct, _iso(ts), cfg.risk.leverage)
                trades.append(fill)

        price_history.append(prices)
        equity_curve.append(cash + sum(state.position_value(positions[s], prices[s]) for s in symbols))

    buy_hold_curve = _buy_hold_curve(price_history, symbols, cfg)
    summary = metrics.summarize(equity_curve, buy_hold_curve, len(trades))
    return {"metrics": summary, "equity_curve": equity_curve,
            "buy_hold_curve": buy_hold_curve, "trades": trades, "timeline": timeline}


# Every strategy except "hybrid" is rule-based (no LLM); only hybrid triggers the cost warning.
DETERMINISTIC = {"indicator_rule", "sentiment_rule", "ma_cross", "macd_cross", "rsi_reversion", "bollinger"}


def _to_ms(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _write_equity(result, path):
    eq = result["equity_curve"]
    bh = result["buy_hold_curve"]
    n_bars = len(eq) - 1                                         # post-warmup bars
    ts = result["timeline"][-n_bars:] if n_bars > 0 else []      # tail aligns with bars
    lines = ["ts,equity,buy_hold", f",{eq[0]},{bh[0]}"]          # baseline row (no ts)
    for i, t in enumerate(ts):
        lines.append(f"{t},{eq[i + 1]},{bh[i + 1]}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _print_summary(m, symbols, strategy, timeframe):
    verdict = "BEATS hold" if m["beats_hold"] else "loses to hold"
    print(
        f"\nBacktest: {strategy} on {','.join(symbols)} ({timeframe})\n"
        f"  final equity     {m['final_equity']:.2f}\n"
        f"  total return     {m['total_return'] * 100:+.2f}%\n"
        f"  buy & hold       {m['buy_hold_return'] * 100:+.2f}%   -> {verdict}\n"
        f"  max drawdown     {m['max_drawdown'] * 100:.2f}%\n"
        f"  trades           {m['n_trades']}\n"
    )


def main(argv=None):
    cfg = load_config()
    p = argparse.ArgumentParser(prog="engine.backtest")
    p.add_argument("--symbols", default=",".join(cfg.symbols))
    p.add_argument("--timeframe", default=cfg.timeframe)
    p.add_argument("--since", required=True)
    p.add_argument("--until", default=None)
    p.add_argument("--strategy", default=cfg.strategy)
    p.add_argument("--capital", type=float, default=cfg.paper_capital)
    p.add_argument("--out", default="data/backtest_equity.csv")
    args = p.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    since_ms = _to_ms(args.since)
    until_ms = _to_ms(args.until) if args.until else int(time.time() * 1000)
    cfg.symbols, cfg.timeframe, cfg.strategy, cfg.paper_capital = (
        symbols, args.timeframe, args.strategy, args.capital)

    if args.strategy not in DETERMINISTIC:
        print(f"WARNING: strategy '{args.strategy}' is not deterministic — it makes "
              f"~1 LLM call per candle per symbol ({len(symbols)} symbol(s)); "
              f"this can be slow and costly. The cheap path is 'indicator_rule'.")

    exchange = market.make_exchange(cfg.exchange)
    result = run_backtest(symbols, args.timeframe, since_ms, until_ms,
                          args.strategy, cfg, exchange=exchange)
    _print_summary(result["metrics"], symbols, args.strategy, args.timeframe)
    _write_equity(result, args.out)
    return result


if __name__ == "__main__":
    main()
