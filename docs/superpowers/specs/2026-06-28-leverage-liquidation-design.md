# Leverage + Liquidation (isolated margin) — Design

**Date:** 2026-06-28
**Status:** Approved
**Sub-project:** 4 of 5 in the v2 roadmap. This is **slice 2 of 3** toward full derivatives:
shorting → **leverage + liquidation** → funding. Slice 1 (signed net position / shorting) is
live on `main`; this slice builds directly on it.

## Goal

Let the bot trade with **leverage > 1×** and be **liquidated** when an adverse move erodes a
position's margin — the two things slice 1 deliberately left out. Leverage is **opt-in**
(`leverage`, default `1.0`), so every existing setup stays unleveraged and, on the default spot
exchange (`allow_short` auto-off), **byte-for-byte unchanged**.

This adopts the **standard isolated-margin perp model**: each position posts its own margin and
liquidates on its own at its own liquidation price — no coupling between symbols. It reuses the
engine's existing per-symbol force-close path (the stop-loss machinery) so liquidation is just a
second trigger price, not a new control flow.

Non-goals (out of scope): cross margin, per-symbol leverage, an insurance fund / partial-
liquidation tiers / bankruptcy socialization beyond a defensive cash clamp, and funding rates
(funding is slice 3).

## Model (isolated margin, generalizes slice 1)

The unit of account is **equity**, not raw cash. A position holds **margin** internally; cash is
the *free* balance after margin is locked.

- **Margin posted by a position = `|qty| · avg_price / leverage`** — derived, not a new stored
  field. The only new state is `leverage` on the position.
- **Open / extend** the current direction: lock `added_notional / leverage` of cash
  (`added_notional = filled · eff_price`); the rest is borrowed. `avg_price` weighted-averages the
  entry; total margin stays consistent (`|new_qty|·avg_new/L = old_margin + filled·eff/L`).
- **Close / reduce** toward flat: return `released_margin + realized_P&L − fee` to cash, where
  `released_margin = filled · avg_price / leverage` and
  `realized_P&L = filled·(eff − avg)` for a long close, `filled·(avg − eff)` for a cover.
- **Equity (`engine/state.py`)** changes from `cash + Σ qty·price` to the margin-aware
  **`cash + Σ ( |qty_i|·avg_i/L_i + qty_i·(price_i − avg_i) )`** = `cash + Σ (margin_i +
  unrealized_i)`. For any **all-long** book this is algebraically identical to the old formula, so
  the live equity curve is unchanged; it only differs once a short exists (brand-new, opt-in).

### Equivalence / compatibility at `leverage = 1`

- A **long** at `L = 1`: margin = full notional, so open spends full cash and close returns full
  exit notional — **identical to today** (cash trajectory and all).
- A **short** at `L = 1`: economically identical (same equity, same P&L) but the **cash bookkeeping
  differs** from slice 1. Slice 1 used a spot-style "sell-to-open receives full proceeds" model
  (cash went *up* on a short open, and a short could open from a **zero-cash** account). Isolated
  margin instead **locks collateral** (cash goes *down* by the margin). This is the one real
  semantic tightening: **an isolated short requires margin to open.** Because shorting is itself
  opt-in and only landed in slice 1, no deployed setup relies on zero-collateral shorts; and the
  default config (spot exchange → `allow_short` auto-off) never opens a short, so **live default
  behavior is byte-identical.** A handful of slice-1 short *cash-value* assertions are updated to
  the isolated values; their P&L/equity assertions stand.

## The risk gate (`engine/broker.py plan_order`)

Signature unchanged: `plan_order(decision, position, cash, price, equity, risk)`. `risk` now also
carries `leverage` and `maintenance_margin_pct`. Let `L = max(1.0, risk.leverage)`.

- `max_value = risk.max_position_pct · equity · L` — the magnitude cap on `|qty·price|`, now scaled
  by leverage.
- **`buy`**:
  - `qty < 0` (cover) → clamp at flat: `q = min(decision.size·equity·L/price, −qty)`. (A cover
    releases margin; no cash constraint.)
  - else (open/extend long) → `notional = min(decision.size·equity·L, long_headroom, cash·L)`,
    `long_headroom = max(0, max_value − qty·price)`. The `cash·L` term is the margin constraint
    (`margin = notional/L ≤ cash`).
- **`sell`**:
  - `qty > 0` (reduce long) → `q = min(decision.size·qty, qty)` — unchanged.
  - else if `risk.allow_short` (open/extend short) →
    `notional = min(decision.size·equity·L, short_headroom, cash·L)`,
    `short_headroom = max(0, max_value − (−qty)·price)`. **New vs slice 1:** the short open is now
    margin-constrained by `cash·L` (slice 1 had no cash constraint on shorts).
  - else → `None` (spot long-only, unchanged).

At `L = 1` every branch reduces to slice 1 exactly **except** the short-open cash constraint —
which is the intended tightening above.

## Fills (`engine/broker.py apply_fill`)

`apply_fill` gains a `leverage` parameter and switches to margin accounting:

- The position's working leverage `L` = `position.leverage` when it already has a position
  (`|qty| > eps`), else `max(1.0, leverage)` (config) for a fresh open.
- **buy**: `eff = price·(1+slippage)`.
  - **open/extend long** (`old_qty ≥ 0`): margin-clamp defensively
    (`filled ≤ cash·L/eff`); `cash −= filled·eff/L + fee`; weighted-avg the entry; set `leverage = L`.
  - **cover** (`old_qty < 0`): clamp at flat; `cash += released_margin + realized_P&L − fee`
    (`released = filled·avg/L`, `realized = filled·(avg − eff)`). Covers release margin, so they
    never need cash up front; the **only** way cash would dip below 0 is a gap *past* the
    liquidation price (bad debt) → defensively **clamp cash to ≥ 0** with a `# ponytail:` note
    (insurance fund is the upgrade path).
- **sell**: `eff = price·(1−slippage)`.
  - **open/extend short** (`old_qty ≤ 0`): `cash −= filled·eff/L + fee` (lock margin); weighted-avg;
    set `leverage = L`.
  - **reduce long** (`old_qty > 0`): `cash += released_margin + realized_P&L − fee`
    (`released = filled·avg/L`, `realized = filled·(eff − avg)`).
- **Reaching flat** resets the position to zeros (`leverage` back to `1.0`).
- **Direction flip** in one fill (gate clamps at flat, so this is defensive / direct-call only):
  close the old side (release its margin + realized P&L) then open the new side at `eff` with the
  config leverage. `avg_price = eff`, directional stop off `eff`.
- The old slice-1 cash clamp (forced partial fill, no crash) is preserved in spirit: opens are
  margin-clamped; covers/closes are clamped to keep cash ≥ 0.

## Stops + liquidation (`engine/broker.py`)

- `stop_triggered(position, price)` — unchanged (long fires `price ≤ stop`, short `price ≥ stop`).
- **`liquidation_price(position, maintenance_margin_pct) -> float`**:
  - `L = position.leverage`, `mmr = maintenance_margin_pct`, `avg = position.avg_price`.
  - `L ≤ 1` or flat or `avg ≤ 0` → `0.0` (never liquidated; the stop-loss is the protection).
  - long (`qty > 0`): `avg·(1 − 1/L)/(1 − mmr)`.
  - short (`qty < 0`): `avg·(1 + 1/L)/(1 + mmr)`.
- **`force_close(position, price, risk) -> Optional[str]`** — the single entry point the loop uses:
  - returns `"liquidation"` if the liquidation price is hit (long `price ≤ liq`, short
    `price ≥ liq`, with `liq > 0`), checked **first** (more severe);
  - else `"stop-loss"` if `stop_triggered`;
  - else `None`.

The 5% protective stop still fires before liquidation on low leverage; liquidation only bites when
`1/L < stop_loss_pct` (high leverage) or a gap jumps straight past the stop.

## Loop wiring (`engine/bot.py`, `engine/backtest.py`)

Both already resolve `allow_short` from the exchange once after `make_exchange`; leverage/mmr come
straight from config (no resolution needed). The per-symbol force-close block changes from
`if stop_triggered(...)` to:

```
reason = broker.force_close(pos, price, cfg.risk)
if reason:                              # "liquidation" | "stop-loss"
    close = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
    order = close
else:
    decision = strategy(...); order = plan_order(...); reason = decision.reason
```

`apply_fill` is called with the new `leverage` argument (`cfg.risk.leverage`). The decision-log
`reason` now records `"liquidation"` distinctly from `"stop-loss"`.

## Config + persistence

- `engine/config.py RiskConfig`: `leverage: float = 1.0`, `maintenance_margin_pct: float = 0.005`;
  `load_config` reads `raw["risk"].get("leverage", 1.0)` and `.get("maintenance_margin_pct", 0.005)`.
- `engine/config.yaml`: `risk:` block leaves both at defaults (documented, commented).
- `engine/state.py`: persist `leverage` on each position (default `1.0` when absent, so old
  `state.json` snapshots load cleanly); the **equity** function switches to the margin-aware
  formula above; the saved snapshot adds a computed **`liq_price`** per position (via
  `broker.liquidation_price`) for the dashboard.

## Dashboard (`desktop/`)

`PositionsTable` gains two read-only columns: **Leverage** (e.g. `5×`, blank/`1×` when unleveraged)
and **Liq. price** (the snapshot's `liq_price`, blank when `0`). No TS math — the engine writes the
liquidation price into the snapshot. The equity curve already uses the engine's signed equity.

## Brain + strategies

**No strategy code changes.** Leverage and liquidation are pure risk-gate / accounting mechanics;
`indicator_rule` / `sentiment_rule` / `hybrid` emit the same buy/sell/hold. The LLM prompt does not
need a leverage clause for slice 2 (sizing is `decision.size ∈ [0,1]`; the gate scales by leverage).
`# ponytail: the model proposes direction+size; leverage is a deterministic gate knob, not an LLM
decision — keep it out of the prompt until there's a reason.`

## Safety properties

- The gate stays the **single authority**: `max_value` scales by leverage; opens are margin-bounded
  (`notional ≤ cash·L`); no path lets `|exposure|` exceed `max_value`.
- **Isolated**: each position's liquidation depends only on its own `avg`, `leverage`, `mmr` — no
  cross-symbol coupling, no cascade.
- **`leverage = 1` ⇒ unchanged** for longs (and for the default spot/`allow_short`-off config, the
  whole live behavior is byte-identical).
- Liquidation is checked **before** the strategy every cycle and reuses the proven force-close path;
  fail-safe HOLD on any error is unchanged.
- A gap past the liquidation price (bad debt) **cannot crash or drive cash negative** — the cover
  fill clamps cash to ≥ 0 (documented bad-debt socialization; insurance fund is the upgrade).
- Backtest inherits leverage + liquidation for free (same gate, same force-close helper).

## Testing

`tests/test_broker.py` (extend):
- **gate**: `leverage = 5` raises `max_value` 5× (a buy can open 5× the unleveraged notional, capped
  by `cash·L`); a long open is bounded by `cash·L`; short open now bounded by `cash·L`.
- **apply_fill margin accounting**: open long `L = 5` locks `notional/5` margin (cash drops by margin
  + fee, not full notional); close returns `margin + realized − fee`; full long round-trip P&L at
  `L = 5` matches the unleveraged P&L (leverage doesn't change absolute P&L, only margin); short
  round-trip at `L = 1` matches slice-1 **equity/P&L** (cash-value assertions updated to isolated).
- **liquidation_price**: long/short formulas at a sample `L`/`mmr`; `L ≤ 1` → `0`; flat → `0`.
- **force_close**: returns `"liquidation"` when price crosses the liq price (long below / short
  above); returns `"stop-loss"` when only the stop is hit; liquidation outranks the stop; `None`
  otherwise.
- **bad-debt clamp**: a cover at a price gapped past liquidation leaves `cash ≥ 0`, no crash.
- **equity (`test_state.py`)**: margin-aware equity equals the old `cash + Σ qty·price` for an
  all-long book; a leveraged long's equity tracks `cash + margin + unrealized`.

`tests/test_bot.py` / `tests/test_backtest.py`: with `leverage > 1` and an adverse move, a position
is force-closed with reason `"liquidation"` end-to-end; unleveraged paths unchanged.

`desktop` vitest: `PositionsTable` renders the Leverage and Liq. price columns (a leveraged row shows
`5×` + a liq price; an unleveraged row shows them blank/`1×`).

## Files

| file | change |
|---|---|
| `engine/config.py`, `engine/config.yaml` | `RiskConfig.leverage = 1.0`, `maintenance_margin_pct = 0.005`; `risk:` block documents both |
| `engine/models.py` | `Position.leverage: float = 1.0` |
| `engine/broker.py` | `plan_order` leverage-scaled cap + margin-bounded opens; `apply_fill` margin accounting + `leverage` arg; `+ liquidation_price`; `+ force_close` |
| `engine/state.py` | margin-aware `equity`; persist `leverage`; write computed `liq_price` into the snapshot |
| `engine/bot.py`, `engine/backtest.py` | use `force_close` (liquidation outranks stop); pass `leverage` to `apply_fill` |
| `desktop/src/renderer/src/components/PositionsTable.tsx` | + Leverage and Liq. price columns |
| tests (`test_broker`, `test_state`, `test_bot`, `test_backtest`, desktop `PositionsTable`) | as above |
| `README.md` | note leverage + `maintenance_margin_pct` (opt-in, isolated margin, liquidation) |

No new dependencies. Models keep their shape (`Position` gains one defaulted field). `indicators` /
`strategies` / `sentiment` logic untouched.
