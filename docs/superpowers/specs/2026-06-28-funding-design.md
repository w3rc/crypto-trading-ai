# Funding Rates (discrete, isolated-margin perp) — Design

**Date:** 2026-06-28
**Status:** Approved
**Sub-project:** 4 of 5 in the v2 roadmap. This is **slice 3 of 3** — the last derivatives piece:
shorting → leverage + liquidation → **funding**. Slices 1 (signed position) and 2 (leverage +
liquidation) are live on `main`; this slice builds directly on them.

## Goal

Add **funding** — the periodic payment perpetual-futures positions exchange to keep the perp
tethered to spot. It is **opt-in** (`funding_rate`, default `0.0` = off), so every existing setup
is **byte-identical** until the rate is set. It completes the derivatives model: a leveraged perp
position now also bleeds (or earns) funding for as long as it's held.

The mechanic is one signed cash flow per position per funding interval, applied discretely (every
`funding_interval_hours`, default 8h) the way real exchanges charge it.

Non-goals (out of scope, upgrade paths): live ccxt funding-rate fetch (a configured constant is
used), per-position margin deduction that shifts the isolated liquidation price (funding is an
account-level cash flow here), multi-interval catch-up if the bot was down across several
boundaries, and any dashboard funding indicator.

## Model (matches one-way perp funding)

- **Payment:** `funding_payment(position, price, funding_rate) = −funding_rate · qty · price`
  — the signed cash delta a position receives (positive) or pays (negative). With a **positive**
  rate, longs (`qty > 0`) pay and shorts (`qty < 0`) receive; with a negative rate the reverse.
  A flat position pays/receives nothing. Magnitude is `|funding_rate| · |notional|`, matching the
  exchange convention (funding = rate × position value).
- **Discrete timing:** funding lands once per `funding_interval_hours` boundary crossing. The bot
  runs on an external cron cadence, so the only reliable clock is the persisted last-funding time;
  the backtest reads it from bar timestamps.
- **Account-level cash flow:** funding debits/credits **cash**, clamped `≥ 0` (the same bad-debt
  guard `apply_fill` uses). It therefore lowers/raises **equity** (`cash + Σ position_value`), but
  the **entry-based liquidation price does not move** — funding drains the account rather than
  shifting each position's isolated liq price. (Real isolated margin deducts funding from the
  position's own margin and moves its liq; that's the documented refinement.) Consequence: funding
  alone never trips `force_close` in slice 3; it bleeds cash/equity over time.

## Pure functions (`engine/broker.py`)

Two additive, pure functions — no change to any existing broker behavior:

- `funding_payment(position, price, funding_rate) -> float` — `−funding_rate · position.qty · price`.
  Flat (`qty == 0`) → `0.0`.
- `funding_due(last_ms, now_ms, interval_hours) -> bool` — `last_ms is not None and
  (now_ms − last_ms) >= interval_hours · 3_600_000`. Pure epoch-millisecond arithmetic (no
  `datetime` import in broker). `last_ms is None` → `False` (first observation initializes, never
  pays on the same tick).

## State (`engine/state.py`)

`State` gains `last_funding_ts: Optional[str] = None` (an ISO timestamp string, consistent with
`equity_history` ts):
- `load_state` reads `raw.get("last_funding_ts")` — an old `state.json` without the key loads as
  `None` (backward-compatible).
- `save_state_atomic` writes it into the payload.

The backtest does **not** persist state, so it tracks the last-funding time as a local epoch-ms
variable instead.

## Loop wiring (`engine/bot.py`, `engine/backtest.py`)

Everything below is gated on **`cfg.risk.funding_rate != 0`** — with funding off, no time is
tracked, no cash moves, and both loops are byte-identical to today.

**Bot (`run_once`):**
- `now_ms` = the cycle timestamp in epoch ms (`datetime.fromisoformat(ts).timestamp() * 1000`,
  reusing the existing `ts = _now()`).
- `last_ms` = `datetime.fromisoformat(st.last_funding_ts).timestamp() * 1000` when set, else `None`.
- `due = broker.funding_due(last_ms, now_ms, cfg.risk.funding_interval_hours)`.
- Inside the per-symbol block, right after `prices[sym] = price` and **before** `state.equity(...)`
  / `force_close` (so equity-for-sizing and the cycle reflect the payment): if `due` and
  `pos.qty != 0`, `st.cash = max(0.0, st.cash + broker.funding_payment(pos, price, rate))` and
  print a funding line.
- After the loop, advance the clock: if `st.last_funding_ts is None or due:` set
  `st.last_funding_ts = ts` (initializes on the first enabled cycle, advances on every crossing).
  This is inside the existing `if prices:` block so a fully-skipped cycle doesn't stamp a time.

**Backtest (`run_backtest`):**
- A local `last_funding_ms = None`.
- Each bar (which already has an epoch-ms `ts`): `due = funding_rate != 0 and
  broker.funding_due(last_funding_ms, ts, interval)`. Apply per symbol exactly as the bot does,
  right before the equity-for-sizing line. Then `if last_funding_ms is None or due:
  last_funding_ms = ts` (initializes on the first bar, advances every crossing — funding lands
  every `interval/bar_hours` bars).

The decision log / trade log are unchanged; funding is a cash effect that surfaces in the equity
curve and the printed cycle summary. (A dedicated funding log is a deliberate non-goal.)

## Config (`engine/config.py`, `engine/config.yaml`)

`RiskConfig` gains:
- `funding_rate: float = 0.0`
- `funding_interval_hours: float = 8.0`

`load_config` reads `raw["risk"].get("funding_rate", 0.0)` and
`raw["risk"].get("funding_interval_hours", 8.0)`, both `float()`-coerced. `config.yaml` documents
both as commented knobs under `risk:`. Any small signed `funding_rate` is valid; the default
`funding_interval_hours = 8.0` is used unless overridden. A degenerate `funding_interval_hours <= 0`
would simply make funding land every cycle (`now − last >= 0` always true) — harmless given the
`max(0.0, …)` cash clamp, and the user's explicit choice; no clamp is added.

## Brain + strategies + dashboard

- **No strategy / LLM changes.** Funding is pure accounting; it doesn't enter a decision.
- **No dashboard change.** Funding moves cash/equity, already rendered by the equity curve and the
  Account KPIs. (A cumulative-funding indicator is a noted non-goal.)

## Safety properties

- **`funding_rate = 0` ⇒ byte-identical** to the current engine — the whole path is gated off,
  no `last_funding_ts` is written, no cash moves. The existing suite proves it.
- Funding **cannot drive cash negative or crash**: the `max(0.0, …)` clamp mirrors the apply_fill
  bad-debt guard.
- The risk gate, `apply_fill`, and the entry-based liquidation price are **unchanged** — funding is
  layered on as a cash flow, not a change to order sizing or the fill engine.
- Backtest inherits funding through the same pure functions; with funding off its curves are
  unchanged.
- Fail-safe HOLD on any error is unchanged (funding application is simple arithmetic on already-
  fetched price; it sits inside the existing per-symbol try only to the extent the price fetch does).

## Testing

`tests/test_broker.py` (extend):
- `funding_payment`: positive rate → long (`qty>0`) pays (negative delta), short (`qty<0`) receives
  (positive delta); negative rate flips both; flat → `0.0`; magnitude `= |rate · qty · price|`.
- `funding_due`: `now − last` just under the interval → `False`; at/over → `True`; `last_ms None`
  → `False`.

`tests/test_state.py` (extend):
- `last_funding_ts` round-trips through save/load; absent in an old snapshot → `None`.

`tests/test_bot.py` (extend):
- funding on (`funding_rate > 0`), a held **long**, `last_funding_ts` seeded > one interval ago →
  cash drops by `rate · qty · price` and `last_funding_ts` advances; a **short** gains; funding off
  (`rate == 0`) → cash unchanged and no `last_funding_ts` written (existing tests stay byte-identical).

`tests/test_backtest.py` (extend):
- a multi-bar held long with `funding_rate > 0` ends with lower equity than the same run at
  `funding_rate == 0` (funding bled the position); curves stay aligned.

## Files

| file | change |
|---|---|
| `engine/config.py`, `engine/config.yaml` | `RiskConfig.funding_rate = 0.0`, `funding_interval_hours = 8.0`; `risk:` block documents both |
| `engine/broker.py` | `+ funding_payment`, `+ funding_due` (pure, additive) |
| `engine/state.py` | `State.last_funding_ts: Optional[str] = None`; load/save it |
| `engine/bot.py` | apply funding per cycle when due (gated on `funding_rate != 0`); track `last_funding_ts` |
| `engine/backtest.py` | apply funding per bar when due; track `last_funding_ms` locally |
| tests (`test_broker`, `test_state`, `test_bot`, `test_backtest`) | as above |
| `README.md` | document funding (opt-in, discrete interval, account cash flow) |

No new dependencies. No change to `models`/`indicators`/`strategies`/`sentiment`/`metrics`/
`datafeed`/`market`/`llm`. `Position`/`Order`/`Fill` shapes unchanged.
