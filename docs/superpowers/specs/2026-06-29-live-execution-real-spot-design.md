# Live Execution — Slice 2: Real Spot Execution (design)

**Status:** approved 2026-06-29
**Prereq:** Slice 1 (shadow mode) — merged (`f388c80`). Shadow already reads real balance + price
via `market.fetch_balance` and runs the authoritative `broker.plan_order` gate, logging intended
orders with `executed: false`. Slice 2 adds the one thing shadow deliberately lacks: actually
placing the order.

## Goal

A `mode: "live"` that places **real spot market orders**, **long-only**, with the **exchange as the
source of truth** for cash and position quantity. It is gated by two independent switches so it
cannot trip by accident, and stopped instantly by a kill file. This is the first time real money
moves; the design is safety-first.

## Non-goals (later slices)

Shorting / leverage / derivatives / funding **in live** (those remain paper-only); limit orders;
multi-quote accounts; partial-fill chasing / order-replacement; a dashboard arm/halt button. Live is
spot, long-only, market orders.

## Architecture

A new `mode: "live"` joins `paper` (default) and `shadow`. `run_once` routes:

```
mode == "live"  AND armed     -> _run_live   (HALT checked first inside; places real orders)
mode == "live"  AND NOT armed -> _run_shadow (logs intent, places nothing)
mode == "shadow"              -> _run_shadow
else                          -> paper path (byte-identical, unchanged)
```

- **armed** = `cfg.mode == "live"` AND `os.environ.get("LIVE_TRADING_ARMED") == "yes"`.
  Two independent switches (config + env); missing either ⇒ falls back to shadow. A stale committed
  `mode: live` alone never trades.
- **halted** = `data/HALT` file exists. Checked **first** inside the live path; present ⇒ no
  execution this cycle, status written (`halted: true`), return. `touch data/HALT` stops trading
  from anywhere, survives restarts; `rm data/HALT` resumes.
- On every armed, non-halted live run, a loud one-line banner prints
  (`LIVE — placing real orders on <exchange>`). Live is never silent.

`_run_live` is a self-contained function parallel to `_run_shadow`. The paper and shadow paths are
untouched.

## Source of truth — exchange-as-truth + sidecar

The exchange is truth for **cash** and **position quantity** (re-read every cycle via the existing
`market.fetch_balance`). `avg_price` and `stop_price` — bot-only concepts the exchange does not
store — live in a small local sidecar `data/live_meta.json`:

```json
{ "BTC/USDT": { "avg_price": 64000.0, "stop_price": 60800.0 } }
```

The sidecar is updated from each **real** fill. Consequence: a crash, a partial fill, fees, or a
manual trade on the account never desync qty/cash — next cycle simply re-reads the real balance. The
only thing a lost sidecar costs is a stale stop (recomputed on next entry; worst case a position
shows no protective stop until then). `state.json` becomes a **read-only mirror** (real balances +
sidecar avg/stop + appended equity history) so the existing dashboard renders live positions.

## `_run_live` cycle

1. `acquire_lock(data_dir)`.
2. **Kill check:** `data/HALT` exists ⇒ log, write status (`mode: live`, `halted: true`), return.
3. **Arm check** happens in routing (above); if we are here, we are armed. Print the banner.
4. **Read truth:** `cash, qty_by = market.fetch_balance(exchange, symbols)`. Load `live_meta.json`.
   Build `Position(sym, qty=qty_by[sym], avg_price=meta.avg, stop_price=meta.stop)` per symbol.
   - **Fail closed:** balance fetch raises ⇒ log, write status, return. No orders without a known
     balance.
5. Per symbol (one bad symbol never aborts the cycle — `try/except`, skip on error):
   - `fetch_ohlcv_df` + `compute_indicators` + `fetch_price` (skip symbol if price ≤ 0).
   - `equity` = real cash + Σ real qty·price.
   - **Exits first:** `broker.force_close(pos, price, cfg.risk)`. Spot (leverage 1) can only return
     `"stop-loss"` (liquidation requires leverage > 1, so `liquidation_price` is 0). Stop fired ⇒
     `order = Order("sell", pos.qty, price)`.
   - Else: `decision = strategy(...)`; `order = broker.plan_order(decision, pos, cash, price,
     equity, cfg.risk)`. Long-only (spot ⇒ `allow_short` false ⇒ a sell only reduces a long).
   - `order is None` ⇒ `append_decision(executed=False)`, log HOLD, continue.
   - **Precision / min-notional guard:** round `order.qty` to exchange precision; if the resulting
     notional is below the exchange's min cost, skip (`append_decision(executed=False)`, log "below
     min notional"). Prevents an exchange rejection from crashing the cycle.
   - **Place:** `fill = market.create_order(exchange, sym, order.side, qty)` — a real **market**
     order. Reconcile the **actual** fill (filled qty, average price, fee) from the ccxt response,
     with one `fetch_order` re-poll if the response lacks fill detail.
   - **Record:** `append_trade(real_fill)`; `append_decision(executed=True)`; update the sidecar:
     - buy that opens/extends: `new_avg = (old_qty·old_avg + filled·fill_price) / (old_qty+filled)`;
       `stop = new_avg·(1 - stop_loss_pct)`.
     - sell to flat: clear the symbol's sidecar entry.
     - partial reduce: keep avg, keep stop.
6. After the loop: write `status.json` (`mode: live`, `halted: false`) and a read-only `state.json`
   mirror (real cash/qty + sidecar avg/stop + appended equity point) via `save_state_atomic`.

## New / changed interfaces

- `engine/market.py`: `create_order(exchange, symbol, side, qty) -> Fill` — places a real market
  order and returns the reconciled real fill (filled qty, average price, fee). **The only place
  `create_order` is called in the engine**, reachable only on the live+armed+not-halted path.
- `engine/bot.py`: `_live_armed()` helper; `_run_live(cfg, market, strategy)`; routing branch;
  `_status_payload` gains `halted` (paper/shadow write `false`).
- `engine/state.py`: `load_live_meta(data_dir)` / `save_live_meta(meta, data_dir)` (atomic, like
  `write_status`); `live_meta_update(...)` helper for the avg/stop recompute, or inline in the bot.
- `engine/config.py` / `config.yaml`: document `mode: live` and `LIVE_TRADING_ARMED`. (Credential
  resolution from slice 1 is reused unchanged — live uses the same `EXCHANGE_API_KEY` /
  `EXCHANGE_API_SECRET`, which must now be a **trade-enabled** key.)
- `desktop/src/lib/parse.ts`: `Status.halted?: boolean`.
- `desktop/src/renderer/src/components/StatusStrip.tsx`: a `HALTED` indicator when
  `status.halted` is true; the Mode chip already shows `LIVE`.

## Defaults (chosen, approved)

- **Market orders** (not limit) — matches shadow's fill-at-current-price assumption; simplest MVP.
- **Spot, long-only** — no short/leverage/funding live.
- **Fee + reconciliation best-effort** — cash truth is re-read from the exchange next cycle, so a
  fee-column imprecision or an under-recorded partial fill self-heals. `ponytail:` single re-poll,
  no chase loop. Upgrade path: poll-until-closed + exchange fee statement.
- **Fail closed** on balance-fetch error (no orders without a known balance).

## Error handling

- Balance fetch fails ⇒ no orders, status written, cycle returns cleanly.
- One symbol's data/price/order error ⇒ logged, that symbol skipped, others proceed.
- `create_order` raises (insufficient funds, exchange down, rejected) ⇒ logged, that symbol skipped
  (`append_decision(executed=False)` with the error), no `state.json` corruption (truth is the
  exchange, re-read next cycle).
- `HALT` present ⇒ hard stop before any order.

## Security

- Credentials are env-only (`EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`), already `repr=False` on the
  `Config` fields from slice 1. Never committed, never echoed. README warns the live key must be
  **trade-enabled but withdrawal-disabled**.
- The two-switch arm + kill file make accidental live trading require two deliberate actions
  (config edit + env export) and make stopping a single action (`touch data/HALT`).

## Testing (TDD, red → green)

- **config:** `LIVE_TRADING_ARMED` / `mode: live` plumbing if any (mostly reuses slice 1).
- **market:** `create_order` reconciles a fully-filled market order; falls back to `fetch_order`
  when the response lacks fill detail; returns a `Fill` with real price/fee. (Fake ccxt exchange.)
- **bot — the safety core:**
  - `mode: live` + armed + fake exchange ⇒ `create_order` **is** called, real fill in `trades.csv`,
    `executed: true`, sidecar updated, `status.mode == "live"`.
  - `mode: live` + **not** armed ⇒ routes to shadow: no `create_order`, `executed: false`,
    `[shadow]` reason, no `trades.csv`.
  - `data/HALT` present ⇒ no `create_order`, status `halted: true`, returns cleanly.
  - balance fetch fails ⇒ no `create_order`, no crash, status written.
  - below-min-notional ⇒ no `create_order`, `executed: false`.
  - stop-loss fires ⇒ a real sell-to-flat is placed; sidecar entry cleared.
  - **paper + shadow paths byte-identical** (regression).
- **audit:** `grep -rn "create_order" engine/` returns **exactly one** definition + one call site
  (`market.create_order` and its `_run_live` caller) — and that call is unreachable unless
  live+armed+not-halted. (Flips the slice-1 "no create_order" audit.)
- **desktop:** vitest green; `npm run build` exit 0; Playwright shows `MODE: LIVE` and the `HALTED`
  indicator at 1280 / 768 / 375.

## Open / deferred

`live_meta.json` has no lock of its own (it is written inside the bot lock). Multi-process live is
out of scope (the bot lock already serializes cycles). Partial-fill remainder is left as available
balance and naturally re-evaluated next cycle rather than chased.
