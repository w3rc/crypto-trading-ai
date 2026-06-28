# Live Execution — Slice 1: Shadow Mode — Design

**Date:** 2026-06-28
**Status:** Approved
**Sub-project:** 5 of 5 in the v2 roadmap — the only **real-money** path. Decomposed for safety into
**slice 1 (shadow / dry-run)** → slice 2 (real spot execution). This spec covers **slice 1 only**.
Scope is **spot, long-only**; live derivatives (real leverage/shorting/funding) are explicitly out.

## Goal

Let the bot run against your **real exchange account** with **zero execution risk**: connect with
real (read-only) credentials, read your real balance + price, compute the order it *would* place,
and **log it** — placing nothing and mutating no money. This exercises the scary plumbing
(credentials, real balance reads, order construction) before a single cent is at risk, and gives a
true dry-run to validate the bot's behavior against your real account.

It is **opt-in** (`mode: "shadow"`, default `"paper"`). In paper mode the engine is **byte-identical**
to today. The defining safety property: **`create_order` does not exist in the codebase after this
slice** — so "shadow cannot trade" is auditable, not merely promised. Real order placement is slice 2.

## Modes

`mode: "paper" | "shadow"` (config, default `"paper"`):
- **paper** — today's behavior: public exchange (no credentials), simulated `apply_fill`, `state.json`
  is the source of truth. Unchanged.
- **shadow** — authenticated (read-only) exchange; cash + holdings sourced from the **real** account;
  the strategy + risk gate run as normal; the would-be order is **logged**, not executed; no money
  state is mutated.

## Credentials (the first secret surface)

- `config.exchange_api_key_env` / `config.exchange_secret_env` — the **names** of env vars (default
  `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`). The secrets themselves live only in `.env`, which is
  already gitignored; `.env.example` documents the two names. They are read via `os.environ.get(...)`
  exactly like the existing `MYHERMES_API_KEY`.
- In **paper** mode the credentials are never read (public client). In **shadow** they are loaded but
  used only for **read** calls.
- Documentation instructs the user to create a **read-only / no-trade API key** for shadow — defense
  in depth on top of the code-level guarantee.

## Exchange (`engine/market.py`)

- `make_exchange(name, mode="paper")`:
  - `paper` → `getattr(ccxt, name)({"enableRateLimit": True})` (today, unchanged).
  - `shadow` → the same client plus `apiKey` / `secret` from the configured env vars.
  - A missing key/secret in shadow → the client still constructs (ccxt allows it); the first private
    call (`fetch_balance`) is where an auth error would surface, caught by the bot's per-cycle guard.
- `fetch_balance(exchange, symbols) -> tuple[float, dict[str, float]]`:
  - Calls `exchange.fetch_balance()` (read-only) once.
  - Returns `(cash, qty_by_symbol)` where `cash` = the **free** balance of the shared quote asset
    (e.g. `USDT`) and `qty_by_symbol[sym]` = the **free** balance of each symbol's base asset
    (e.g. `BTC` for `BTC/USDT`). Symbols are split on `/` → `(base, quote)`. A missing asset → `0.0`.
  - `# ponytail: assumes one shared quote across symbols (USDT); a multi-quote portfolio is a later refinement.`
- **No `create_order`, no `cancel_order`, no write call is added in this slice.** The shadow path
  touches only `fetch_ohlcv`, `fetch_ticker`, `fetch_balance`.

## Bot (`engine/bot.py`)

`run_once` gains a shadow branch, gated on `cfg.mode == "shadow"`. The paper path is untouched.

- After `make_exchange(cfg.exchange, cfg.mode)`, in shadow: `cash, qty_by_symbol =
  market.fetch_balance(exchange, cfg.symbols)`. These replace the simulated `st.cash` /
  `st.positions[sym].qty` **for the decision** (the real account is the truth in shadow).
- Per symbol: build a `Position(sym, qty=qty_by_symbol.get(sym, 0.0))` (avg_price/stop default 0 —
  shadow does **not** track entry, so there is no stop/liquidation evaluation), fetch the price, run
  `strategy(...)` → `plan_order(decision, pos, cash, price, equity, cfg.risk)` exactly as in paper.
  `equity` = `cash + Σ qty·price` over the real holdings (a plain spot valuation; no margin model in
  shadow).
- Instead of `apply_fill`: record the intended order as a **decision log** entry
  (`{ts, symbol, action, reason: "[shadow] <reason>", price, executed: false}`) and print
  `[SHADOW] would {SIDE} {qty:.6f} {sym} @ ~{price:.2f}` (or `[SHADOW] HOLD …`). **No `apply_fill`,
  no `append_trade`, no money-state mutation, no order placement.**
- `state.json` is **not** written in shadow (no simulated portfolio to persist); the decisions log is
  the shadow record. `status.json` **is** written, carrying `mode: "shadow"` (see below).

The `force_close` (stop/liquidation) override is **skipped** in shadow — it requires entry-price
tracking the real balance doesn't provide. `# ponytail: shadow shows strategy intent only; stop/liq
arrive with real fills in slice 2.`

## Status snapshot + dashboard

- `status.json` gains a top-level **`mode`** field (`"paper"` | `"shadow"`), written by the bot each
  cycle (the status write already exists from the dashboard-completeness work).
- The dashboard **Status strip** (already built) gains a **Mode** chip rendering `mode` — a prominent
  `SHADOW` / `paper` indicator. The `Status` TS type gains `mode: string`. One field, read-only.
- Intended orders already surface in the existing Decisions log (`executed: false`).

## Safety properties

- **`mode: "paper"` (default) ⇒ byte-identical** to today — no credentials read, public client,
  simulated fills, `state.json` truth. The existing suite proves it.
- **Shadow cannot place an order or move money** — auditable: no `create_order`/`cancel_order`/write
  call exists in the codebase after this slice; shadow's only exchange calls are reads; it never
  invokes `apply_fill`/`append_trade`/`save_state_atomic`.
- The authoritative risk gate (`plan_order`) is **unchanged** — shadow runs the same gate; it only
  changes the *source* of cash/qty (real balance) and the *sink* of the order (a log, not a fill).
- Secrets are env-only and gitignored; the shadow credential is documented as read-only/no-trade.
- A failed private call (bad/missing key, network) is caught by the existing per-symbol try/except
  (and a top-level guard around `fetch_balance`) → the cycle logs and continues / exits cleanly; it
  never crashes or places anything.

## Testing

`tests/test_config.py`: `mode` defaults `"paper"`; explicit `"shadow"` loads; `exchange_api_key_env`
/ `exchange_secret_env` default names load.

`tests/test_market.py`: `make_exchange(name, "shadow")` sets `apiKey`/`secret` from env (monkeypatched
env + a fake ccxt constructor); `make_exchange(name, "paper")` sets neither (public). `fetch_balance`
maps a fake `fetch_balance()` dict → `(free quote, {symbol: free base})`; missing asset → `0.0`;
multi-symbol shares the quote as cash.

`tests/test_bot.py`: in shadow mode the bot (a) sources cash/qty from a fake `fetch_balance`,
(b) logs an intended-order decision with `executed=false` and a `[shadow]` reason, (c) writes
`status.json` with `mode="shadow"`, and **(d) never calls `create_order`** — assert via a fake
exchange whose `create_order` raises if touched — and **never** calls `apply_fill`/`append_trade`/
`save_state_atomic` (assert no `trades.csv`/`state.json` written). Paper-mode tests stay unchanged
(`mode` defaults to paper).

`desktop` vitest: the `Status` type gains `mode`; the strip renders the Mode chip (`shadow`/`paper`).

## Files

| file | change |
|---|---|
| `engine/config.py`, `engine/config.yaml` | `Config.mode = "paper"`; `exchange_api_key_env`/`exchange_secret_env` (default names); document `mode` + the env vars |
| `engine/market.py` | `make_exchange(name, mode)` loads creds in shadow; `+ fetch_balance(exchange, symbols)` (read-only) |
| `engine/bot.py` | shadow branch: real balance → decision → log intended order; write `status.json mode`; skip apply_fill/persist/force_close |
| `engine/state.py` | `write_status` payload gains `mode` (bot passes `cfg.mode`) |
| `.env.example` | document `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` (read-only key for shadow) |
| `desktop/src/lib/parse.ts` | `Status` type gains `mode: string` |
| `desktop/src/renderer/src/components/StatusStrip.tsx` | a Mode chip |
| tests (`test_config`, `test_market`, `test_bot`, desktop `status`/`StatusStrip` build) | as above |
| `README.md` | document shadow mode (read-only key, zero execution, the paper→shadow→live path) |

No new dependencies (ccxt already present). No change to `broker`/`indicators`/`strategies`/
`sentiment`/`metrics`/`datafeed`/`llm`. The paper path and the risk gate are untouched.
