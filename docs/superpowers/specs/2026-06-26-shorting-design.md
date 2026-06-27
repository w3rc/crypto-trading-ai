# Shorting (signed net position) — Design

**Date:** 2026-06-26
**Status:** Approved
**Sub-project:** 4 of 5 in the v2 roadmap. This is **slice 1 of 3** toward full derivatives:
**shorting** → leverage + liquidation → funding. Each slice ships to `main` and de-risks the next.

## Goal

Let the bot go **short**, not just long — matching how crypto perpetual-futures exchanges
actually work: **one signed net position per symbol** (one-way mode). `qty > 0` is long,
`qty < 0` is short; `buy` adds, `sell` subtracts. Shorting is **opt-in** (`allow_short`,
default off) so every existing setup stays spot-long-only and byte-for-byte unchanged
until the flag is flipped. No leverage and no liquidation yet — those are slice 2.

This is the deepest change to the engine's safety core: the authoritative risk gate
(`broker.plan_order` + `apply_fill`) currently enforces "spot long-only". This slice
replaces that invariant with a **symmetric exposure cap** while keeping the gate the one
authority.

Non-goals (later slices): leverage > 1×, maintenance margin / liquidation, funding rates,
single-order position flips, hedge mode (simultaneous long+short on one symbol).

## Model (matches ccxt one-way perp positions)

- **`Position.qty` may be negative.** `avg_price` is the (positive) entry price — the
  weighted-average price of the fills that opened the current direction. `stop_price` works
  both ways.
- **`equity = cash + qty·price`** (signed) — already how `state.equity` sums (`qty·price`
  with `qty < 0` contributes negatively), so a short correctly gains as price falls. No
  change needed there.
- **Cash model (spot-margin style, 1× — no borrowed leverage):** opening a short is
  *sell-to-open* → you receive cash and `qty` goes negative; covering is *buy-to-close* →
  you pay cash and `qty` returns toward 0. `cash` may exceed the initial capital after a
  short opens (you received the sale proceeds); `equity` is the source of truth, not `cash`.

## The risk gate — the core change (`engine/broker.py`)

`plan_order(decision, position, cash, price, equity, risk)` keeps its signature. New rules,
gated on `risk.allow_short`:

- `max_position_value = risk.max_position_pct · equity` — a **magnitude** cap on `|qty·price|`.
- **`buy`** (raises `qty`):
  - If `qty < 0` (short open) → **cover only**, clamped so it cannot cross zero in one order
    (`qty_to_buy ≤ -qty`). Sizing `decision.size·equity/price`, capped at `-qty`.
  - Else (flat/long) → open/extend long: `notional = min(decision.size·equity, long_headroom, cash)`,
    `long_headroom = max(0, max_position_value − qty·price)` (today's behavior exactly).
- **`sell`** (lowers `qty`):
  - If `qty > 0` (long) → **reduce only**, clamped at flat (`qty_to_sell ≤ qty`) — today's behavior.
  - Else if `risk.allow_short` (flat/short) → open/extend short:
    `notional = min(decision.size·equity, short_headroom)`,
    `short_headroom = max(0, max_position_value − (−qty)·price)`.
  - Else (`allow_short` off, flat/short) → **return None** — identical to today's spot long-only.

**No single-order flip:** a reducing order clamps at flat; reversing direction therefore takes
one extra cycle (close this bar, open the other side next bar).
`# ponytail: single-order flip is the upgrade path; reduce-then-reverse is simpler + safe and
costs one bar on a reversal.`

When `allow_short` is **off**, every branch above reduces to the current code exactly — so
the existing 116 tests and all live behavior are unchanged.

## Fills (`engine/broker.py apply_fill`)

`apply_fill` allows `qty < 0` and updates `avg_price` by intent:
- **Extending** the current direction (buy while ≥ 0, or sell while ≤ 0): weighted-average the
  entry into `avg_price`; set the directional stop (below entry for long, above for short).
- **Reducing** toward flat (buy while short, sell while long): `avg_price`/`stop_price`
  unchanged; realized P&L flows through `cash`. Reaching flat resets the position to zeros.
- The old `assert order.qty ≤ position.qty` (no-oversell) and `assert spend ≤ cash` invariants
  encode the long-only rule and are **replaced** by the new gate-guaranteed invariant: the
  resulting `|qty·price| ≤ max_position_value`. The hard cash assert is dropped — `cash` now
  reflects realized P&L and may dip on a losing cover.
- **What bounds an adverse short in slice 1 is the existing stop-loss, now bidirectional.** A
  short's stop sits at `avg·(1 + stop_loss_pct)` and `stop_triggered` is checked first every
  cycle, so an adverse move force-closes at ≈ `stop_loss_pct` (5%) — a cover then costs only
  ≈ `1.05×` the proceeds, i.e. a loss of ≈ `0.05·notional` (tiny at the 1× / 0.25-cap sizing),
  and `cash` stays comfortably positive. (Leverage breaks this comfort margin — which is exactly
  why **liquidation arrives with leverage in slice 2**, not here.)

## Stops both directions (`broker.stop_triggered`)

- Long (`qty > 0`): fires when `price ≤ stop_price` (today).
- Short (`qty < 0`): fires when `price ≥ stop_price`.
- `apply_fill` sets `stop_price = avg·(1 − stop_loss_pct)` for a long, `avg·(1 + stop_loss_pct)`
  for a short.

## Config (`engine/config.py`, `config.yaml`)

`RiskConfig` gains `allow_short: bool = False`; the `risk:` block gains `allow_short: false`.
Off by default → opt-in.

## Brain + strategies

- **No strategy code changes.** `indicator_rule` / `sentiment_rule` emit `sell` on a bearish
  signal; with `allow_short` on, a sell while flat now opens a short (and they reverse
  long↔short over cycles). With it off, they stay long-only as today.
- **LLM prompt (`engine/llm.py`):** the hard-coded "You may only go long or flat (no shorting)"
  line becomes conditional — when `allow_short` is on, the prompt permits shorting and explains
  that `sell` opens/extends a short. (The `hybrid` strategy passes `cfg`/`risk` through so the
  prompt can branch.)

## Dashboard (`desktop/`)

`PositionsTable` currently filters `p.qty > 0`, which would **hide shorts**. Change it to show
any `qty ≠ 0`, with a **Long/Short** label and the sign rendered (a short shows a negative qty
or a "Short" badge). Read-only, no other dashboard change. The equity curve and P&L already
work (they use signed `qty·price`).

## Safety properties

- The gate stays the **single authority**: every order still flows through `plan_order` →
  `apply_fill`; the symmetric cap replaces the long-only cap; no path lets `|exposure|` exceed
  `max_position_value`.
- **Opt-in, default off**: with `allow_short=false`, behavior is byte-identical to today
  (the existing suite proves it).
- Backtest inherits shorting for free (it calls the same gate).
- Fail-safe HOLD on any error is unchanged.

## Testing

`tests/test_broker.py` (extend):
- `allow_short=false`: a sell while flat/short → `None` (today's spot long-only, regression-locked).
- `allow_short=true`: sell while flat → short order capped at `max_position_value`; sell while
  short → extends short up to the cap (no overshoot); buy while short → covers, clamped at flat
  (no flip); a sell can't push `|exposure|` past the cap.
- `apply_fill`: open short (cash up, qty negative, avg = entry, stop above), extend short
  (weighted avg), cover partial (avg unchanged, cash reflects P&L), cover to flat (resets).
- short P&L: price falls after a short → equity rises; price rises → equity falls.
- `stop_triggered`: short stop fires at `price ≥ stop_price`, not below.

`tests/test_bot.py` / `tests/test_backtest.py`: with `allow_short=true` a bearish path opens a
short end-to-end through the gate; with it off, unchanged.

`desktop` vitest: `PositionsTable` renders a short row (negative qty / Short label) and still
hides truly-flat (`qty === 0`) positions.

## Files

| file | change |
|---|---|
| `engine/config.py`, `engine/config.yaml` | `+ allow_short` (default false) |
| `engine/broker.py` | `plan_order` symmetric cap + short open/cover; `apply_fill` signed qty + directional stop; `stop_triggered` both ways |
| `engine/llm.py` | prompt's shorting line conditional on `allow_short` |
| `desktop/src/renderer/src/components/PositionsTable.tsx` | show shorts (`qty ≠ 0`) with a Long/Short label |
| tests (`test_broker`, `test_bot`, `test_backtest`, desktop `PositionsTable`) | as above |
| `README.md` | note shorting + `allow_short` |

No new dependencies. No change to `indicators`/`strategies`/`state` logic (only `state.equity`
is reused, already signed-correct). Models: `Position`/`Order` unchanged in shape (`qty` simply
allowed negative).
