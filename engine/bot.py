import logging
import os
from datetime import datetime, timezone

from engine import broker, indicators, market as market_mod, sentiment as sentiment_mod, state as state_mod, strategies as strategies_mod
from engine.config import load_config
from engine.models import Order, Position

log = logging.getLogger("bot")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload(cfg, ts, funding_accrued, last_funding_ts, halted=False):
    return {
        "ts": ts,
        "mode": cfg.mode,
        "halted": halted,
        "armed": _live_armed(),
        "auto_execute": cfg.auto_execute,
        "interval_seconds": cfg.interval_seconds,
        "symbols": list(cfg.symbols),
        "strategy": cfg.strategy,
        "exchange": cfg.exchange,
        "risk": {
            "allow_short": bool(cfg.risk.allow_short),
            "leverage": cfg.risk.leverage,
            "maintenance_margin_pct": cfg.risk.maintenance_margin_pct,
            "funding_rate": cfg.risk.funding_rate,
            "funding_interval_hours": cfg.risk.funding_interval_hours,
            "max_position_pct": cfg.risk.max_position_pct,
            "stop_loss_pct": cfg.risk.stop_loss_pct,
        },
        "funding": {"accrued": funding_accrued, "last_funding_ts": last_funding_ts},
    }


def run_once(cfg=None, market=None, strategy=None, only_symbol=None, forced_decision=None) -> None:
    cfg = cfg or load_config()
    market = market or market_mod
    strategy = strategy or strategies_mod.get(cfg.strategy)

    if cfg.mode == "live":
        if _live_armed():
            _run_live(cfg, market, strategy, only_symbol, forced_decision)
        else:
            log.warning("mode=live but LIVE_TRADING_ARMED != 'yes' -> shadow (no orders placed)")
            _run_shadow(cfg, market, strategy)
        return
    if cfg.mode == "shadow":
        _run_shadow(cfg, market, strategy)
        return

    with state_mod.acquire_lock(cfg.data_dir):
        st = state_mod.load_state(cfg.data_dir, cfg.paper_capital, cfg.symbols)
        pending = state_mod.load_pending(cfg.data_dir)
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
            if only_symbol is not None and sym != only_symbol:
                continue
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
            if reason:                                # "liquidation" | "stop-loss" — ALWAYS executes
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = forced_decision if forced_decision is not None else strategy(feats, pos, st.cash, cfg)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason
                if forced_decision is None and not cfg.auto_execute:   # defer strategy decisions only
                    act = order.side if order else "hold"
                    state_mod.append_decision(
                        {"ts": ts, "symbol": sym, "action": act, "reason": reason,
                         "price": price, "executed": False}, cfg.data_dir)
                    _record_pending(pending, sym, order, decision, price, ts)
                    print(f"[{sym}] PENDING {act} @ {price:.2f} — {reason}")
                    continue
            pending.pop(sym, None)                     # executing/holding now — no stale suggestion

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

        state_mod.save_pending(pending, cfg.data_dir)
        try:                                     # advisory: a status write error never aborts the cycle
            state_mod.write_status(
                _status_payload(cfg, ts, st.funding_accrued, st.last_funding_ts), cfg.data_dir)
        except Exception as e:
            log.warning("status snapshot write failed: %s", e)


def _run_shadow(cfg, market, strategy) -> None:
    """Dry-run against the REAL account: read balance + price, log the order we WOULD place, execute nothing."""
    with state_mod.acquire_lock(cfg.data_dir):
        exchange = market.make_exchange(cfg.exchange, cfg.mode,
                                        cfg.exchange_api_key, cfg.exchange_secret,
                                        wallet=cfg.exchange_wallet, private_key=cfg.exchange_private_key,
                                        testnet=cfg.testnet)
        if cfg.risk.allow_short is None:
            cfg.risk.allow_short = market_mod.supports_short(exchange)
        ts = _now()
        bd = (sentiment_mod.breakdown(cfg.symbols, cfg) if cfg.sentiment.enabled else {})
        try:
            cash, qty_by = market.fetch_balance(exchange, cfg.symbols)
        except Exception as e:                   # bad/missing key or network -> no decisions, no crash
            log.warning("shadow: balance fetch failed: %s", e)
            print(f"[SHADOW] balance unavailable ({e}); sizing with cash=0 and empty positions")
            cash, qty_by = 0.0, {}

        pending = state_mod.load_pending(cfg.data_dir)
        prices: dict[str, float] = {}
        for sym in cfg.symbols:
            try:
                df = market.fetch_ohlcv_df(exchange, sym, cfg.timeframe)
                feats = indicators.compute_indicators(df)
                price = market.fetch_price(exchange, sym)
                if price <= 0:
                    raise ValueError(f"non-positive price: {price}")
            except Exception as e:
                log.warning("skip %s: %s", sym, e)
                print(f"[{sym}] SKIP ({e})")
                continue

            feats["price"] = price
            feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)
            feats["allow_short"] = bool(cfg.risk.allow_short)
            prices[sym] = price
            pos = Position(sym, qty=qty_by.get(sym, 0.0))         # real holding; no entry/stop tracking
            equity = cash + sum(qty_by.get(s, 0.0) * prices.get(s, 0.0) for s in cfg.symbols)
            decision = strategy(feats, pos, cash, cfg)
            order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)

            action = order.side if order else "hold"
            state_mod.append_decision(
                {"ts": ts, "symbol": sym, "action": action,
                 "reason": f"[shadow] {decision.reason}", "price": price, "executed": False},
                cfg.data_dir)
            if order is None:
                print(f"[SHADOW][{sym}] HOLD @ {price:.2f} — {decision.reason}")
            else:
                print(f"[SHADOW][{sym}] would {order.side.upper()} {order.qty:.6f} @ ~{price:.2f}")
            if not cfg.auto_execute:
                _record_pending(pending, sym, order, decision, price, ts)
            else:
                pending.pop(sym, None)

        state_mod.save_pending(pending, cfg.data_dir)
        try:                                     # advisory; mode=shadow, no funding state in shadow
            state_mod.write_status(_status_payload(cfg, ts, 0.0, None), cfg.data_dir)
        except Exception as e:
            log.warning("status snapshot write failed: %s", e)


def _live_armed() -> bool:
    """Second, independent switch: env must explicitly arm live trading."""
    return os.environ.get("LIVE_TRADING_ARMED") == "yes"


def _record_pending(pending: dict, sym: str, order, decision, price: float, ts: str) -> None:
    """Set or clear a deferred suggestion (auto-execute off). Actionable -> store; else drop."""
    if order is not None:
        pending[sym] = {"ts": ts, "action": order.side, "size": decision.size,
                        "reason": decision.reason, "price": price}
    else:
        pending.pop(sym, None)


def _update_meta(meta: dict, sym: str, pos, side: str, fill, stop_loss_pct: float) -> dict:
    """Recompute the sidecar avg/stop from a real fill (long-only spot)."""
    if side == "buy":                                  # open/extend long
        new_qty = pos.qty + fill.qty
        new_avg = ((pos.qty * pos.avg_price + fill.qty * fill.price) / new_qty
                   if new_qty > 0 else fill.price)
        meta[sym] = {"avg_price": new_avg, "stop_price": new_avg * (1 - stop_loss_pct)}
    else:                                              # sell reduces a long
        if pos.qty - fill.qty <= 1e-8:                 # closed to flat
            meta.pop(sym, None)
        else:                                          # partial reduce -> avg/stop unchanged
            meta[sym] = {"avg_price": pos.avg_price, "stop_price": pos.stop_price}
    return meta


def _write_live_mirror(cfg, ts, cash, qty_by, meta, prices) -> None:
    """Read-only state.json mirror so the dashboard shows live positions.

    ponytail: reflects START-of-cycle balances (one-cycle lag after a fill);
    next cycle re-reads the real balance and corrects it. Re-fetch at end if
    instant post-fill display ever matters.
    """
    st = state_mod.load_state(cfg.data_dir, 0.0, cfg.symbols)   # reuse for equity_history
    st.cash = cash
    for sym in cfg.symbols:
        m = meta.get(sym, {})
        st.positions[sym] = Position(sym, qty=qty_by.get(sym, 0.0),
                                     avg_price=m.get("avg_price", 0.0),
                                     stop_price=m.get("stop_price", 0.0))
    if prices:
        total = cash + sum(qty_by.get(s, 0.0) * prices.get(s, 0.0) for s in cfg.symbols)
        st.equity_history.append({"ts": ts, "equity": total})
    state_mod.save_state_atomic(st, cfg.data_dir, cfg.risk.maintenance_margin_pct)


def _run_live(cfg, market, strategy, only_symbol=None, forced_decision=None) -> None:
    """Place REAL spot market orders. Exchange = truth for cash/qty; sidecar = avg/stop."""
    with state_mod.acquire_lock(cfg.data_dir):
        ts = _now()
        if os.path.exists(os.path.join(cfg.data_dir, "HALT")):
            log.warning("data/HALT present -> no live execution this cycle")
            print("[LIVE] HALTED (data/HALT present) — no orders")
            _safe_write_status(cfg, ts, halted=True)
            return

        print(f"[LIVE] placing real orders on {cfg.exchange}")
        exchange = market.make_exchange(cfg.exchange, "live",
                                        cfg.exchange_api_key, cfg.exchange_secret,
                                        wallet=cfg.exchange_wallet, private_key=cfg.exchange_private_key,
                                        testnet=cfg.testnet)
        if cfg.risk.allow_short is None:
            cfg.risk.allow_short = market_mod.supports_short(exchange)
        bd = (sentiment_mod.breakdown(cfg.symbols, cfg) if cfg.sentiment.enabled else {})

        try:
            cash, qty_by = market.fetch_balance(exchange, cfg.symbols)
        except Exception as e:                          # fail closed: no balance -> no orders
            log.warning("live: balance fetch failed: %s", e)
            print(f"[LIVE] balance unavailable ({e}); no orders this cycle")
            _safe_write_status(cfg, ts, halted=False)
            return

        meta = state_mod.load_live_meta(cfg.data_dir)
        pending = state_mod.load_pending(cfg.data_dir)
        prices: dict[str, float] = {}
        halted_mid = False
        for sym in cfg.symbols:
            if only_symbol is not None and sym != only_symbol:
                continue
            try:
                df = market.fetch_ohlcv_df(exchange, sym, cfg.timeframe)
                feats = indicators.compute_indicators(df)
                price = market.fetch_price(exchange, sym)
                if price <= 0:
                    raise ValueError(f"non-positive price: {price}")
            except Exception as e:
                log.warning("skip %s: %s", sym, e)
                print(f"[{sym}] SKIP ({e})")
                continue

            prices[sym] = price
            m = meta.get(sym, {})
            pos = Position(sym, qty=qty_by.get(sym, 0.0),
                           avg_price=m.get("avg_price", 0.0),
                           stop_price=m.get("stop_price", 0.0))
            feats["price"] = price
            feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)
            feats["allow_short"] = bool(cfg.risk.allow_short)
            equity = cash + sum(qty_by.get(s, 0.0) * prices.get(s, 0.0) for s in cfg.symbols)

            reason = broker.force_close(pos, price, cfg.risk)   # spot -> only "stop-loss" can fire; ALWAYS executes
            if reason:
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = forced_decision if forced_decision is not None else strategy(feats, pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
                reason = decision.reason
                if forced_decision is None and not cfg.auto_execute:   # defer strategy decisions only
                    act = order.side if order else "hold"
                    state_mod.append_decision(
                        {"ts": ts, "symbol": sym, "action": act, "reason": reason,
                         "price": price, "executed": False}, cfg.data_dir)
                    _record_pending(pending, sym, order, decision, price, ts)
                    print(f"[LIVE][{sym}] PENDING {act} @ {price:.2f} — {reason}")
                    continue
            pending.pop(sym, None)                     # executing now — no stale suggestion

            if order is None:
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": "hold", "reason": reason,
                     "price": price, "executed": False}, cfg.data_dir)
                print(f"[LIVE][{sym}] HOLD @ {price:.2f} — {reason}")
                continue

            qty = market.clamp_to_market(exchange, sym, order.qty, price)
            if qty <= 0:
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": order.side,
                     "reason": f"below min notional — {reason}", "price": price,
                     "executed": False}, cfg.data_dir)
                print(f"[LIVE][{sym}] SKIP {order.side} {order.qty:.8f} — below min notional")
                continue

            if os.path.exists(os.path.join(cfg.data_dir, "HALT")):   # kill switch can fire mid-cycle
                halted_mid = True
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": order.side,
                     "reason": "halted (data/HALT) before order", "price": price, "executed": False},
                    cfg.data_dir)
                log.warning("data/HALT appeared mid-cycle -> stopping before %s order", sym)
                print(f"[LIVE][{sym}] HALTED mid-cycle — no further orders")
                break

            try:
                fill = market.create_order(exchange, sym, order.side, qty, price, ts)
            except Exception as e:                       # rejected/insufficient/down -> skip symbol
                log.warning("live: order failed %s %s: %s", sym, order.side, e)
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": order.side,
                     "reason": f"order failed: {e}", "price": price, "executed": False}, cfg.data_dir)
                print(f"[LIVE][{sym}] ORDER FAILED ({e})")
                continue

            # fill placed (real money moved): update the safety-critical sidecar and PERSIST it
            # immediately (per fill), so a later-symbol write failure or a crash cannot lose this
            # fill's protective stop. Advisory trade/decision logs come after and never abort.
            meta = _update_meta(meta, sym, pos, order.side, fill, cfg.risk.stop_loss_pct)
            try:
                state_mod.save_live_meta(meta, cfg.data_dir)
            except Exception as e:
                log.error("live: fill placed but sidecar save failed for %s: %s", sym, e)
                print(f"[LIVE][{sym}] WARNING: fill placed but sidecar save failed: {e}")
            try:
                state_mod.append_trade(fill, cfg.data_dir)
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": order.side, "reason": reason,
                     "price": fill.price, "executed": True}, cfg.data_dir)
            except Exception as e:                       # fill is real + sidecar already persisted; record loudly, don't abort
                log.error("live: fill placed but trade/decision log write failed for %s: %s", sym, e)
                print(f"[LIVE][{sym}] WARNING: fill placed but log write failed: {e}")
            print(f"[LIVE][{sym}] {order.side.upper()} {fill.qty:.8f} @ {fill.price:.2f} — {reason}")

        _write_live_mirror(cfg, ts, cash, qty_by, meta, prices)
        state_mod.save_pending(pending, cfg.data_dir)
        _safe_write_status(cfg, ts, halted=halted_mid)


def _safe_write_status(cfg, ts, halted) -> None:
    try:                                     # advisory: a status write error never aborts the cycle
        state_mod.write_status(_status_payload(cfg, ts, 0.0, None, halted=halted), cfg.data_dir)
    except Exception as e:
        log.warning("status snapshot write failed: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from engine.env import load_dotenv
    load_dotenv()
    run_once()
