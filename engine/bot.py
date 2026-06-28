import logging
from datetime import datetime, timezone

from engine import broker, indicators, market as market_mod, sentiment as sentiment_mod, state as state_mod, strategies as strategies_mod
from engine.config import load_config
from engine.models import Order

log = logging.getLogger("bot")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once(cfg=None, market=None, strategy=None) -> None:
    cfg = cfg or load_config()
    market = market or market_mod
    strategy = strategy or strategies_mod.get(cfg.strategy)

    with state_mod.acquire_lock(cfg.data_dir):
        st = state_mod.load_state(cfg.data_dir, cfg.paper_capital, cfg.symbols)
        exchange = market.make_exchange(cfg.exchange)
        if cfg.risk.allow_short is None:
            cfg.risk.allow_short = market_mod.supports_short(exchange)
        prices: dict[str, float] = {}
        ts = _now()
        bd = (sentiment_mod.breakdown(cfg.symbols, cfg)
              if cfg.sentiment.enabled else {})

        funding_on = cfg.risk.funding_rate != 0
        funding_due = False
        if funding_on:
            now_ms = datetime.fromisoformat(ts).timestamp() * 1000
            last_ms = (datetime.fromisoformat(st.last_funding_ts).timestamp() * 1000
                       if st.last_funding_ts else None)
            funding_due = broker.funding_due(last_ms, now_ms, cfg.risk.funding_interval_hours)

        for sym in cfg.symbols:
            try:
                df = market.fetch_ohlcv_df(exchange, sym, cfg.timeframe)
                feats = indicators.compute_indicators(df)
                price = market.fetch_price(exchange, sym)
                if price <= 0:
                    raise ValueError(f"non-positive price: {price}")
            except Exception as e:                  # one bad symbol never aborts the cycle
                log.warning("skip %s: %s", sym, e)
                print(f"[{sym}] SKIP ({e})")
                continue

            feats["price"] = price          # fill/stop use the live ticker, not the stale candle close
            feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)
            feats["allow_short"] = bool(cfg.risk.allow_short)
            prices[sym] = price
            pos = st.positions[sym]
            if funding_due and pos.qty != 0:
                pay = broker.funding_payment(pos, price, cfg.risk.funding_rate)
                st.cash = max(0.0, st.cash + pay)
                st.funding_accrued += pay
                print(f"[{sym}] FUNDING {pay:+.4f}")
            equity = state_mod.equity(st, prices)   # best-effort equity for sizing

            reason = broker.force_close(pos, price, cfg.risk)
            if reason:                                # "liquidation" | "stop-loss"
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strategy(feats, pos, st.cash, cfg)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason

            action = order.side if order else "hold"
            state_mod.append_decision(
                {"ts": ts, "symbol": sym, "action": action, "reason": reason,
                 "price": price, "executed": order is not None},
                cfg.data_dir)

            if order is None:
                print(f"[{sym}] HOLD @ {price:.2f} — {reason}")
                continue

            new_pos, new_cash, fill = broker.apply_fill(
                order, pos, st.cash, cfg.fee_pct, cfg.slippage_pct,
                cfg.risk.stop_loss_pct, ts, cfg.risk.leverage)
            st.positions[sym] = new_pos
            st.cash = new_cash
            state_mod.append_trade(fill, cfg.data_dir)
            print(f"[{sym}] {order.side.upper()} {order.qty:.6f} @ {fill.price:.2f} — {reason}")

        if cfg.sentiment.enabled:
            try:
                state_mod.write_sentiment(
                    {"ts": ts, "strategy": cfg.strategy, "symbols": bd}, cfg.data_dir)
            except Exception as e:                  # advisory: a write error never aborts the cycle
                log.warning("sentiment snapshot write failed: %s", e)

        if prices:
            if funding_on and (st.last_funding_ts is None or funding_due):
                st.last_funding_ts = ts
            total = state_mod.equity(st, prices)
            st.equity_history.append({"ts": ts, "equity": total})
            state_mod.save_state_atomic(st, cfg.data_dir, cfg.risk.maintenance_margin_pct)
            print(f"cash={st.cash:.2f} equity={total:.2f}")
        else:
            print(f"cash={st.cash:.2f} (no symbols priced this cycle)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
