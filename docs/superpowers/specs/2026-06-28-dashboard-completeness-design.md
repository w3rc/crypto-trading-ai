# Dashboard Completeness — Design

**Date:** 2026-06-28
**Status:** Approved
**Sub-project:** v2 roadmap — makes the desktop dashboard reflect the **full** paper-trading
feature set before any move to live execution. Surfaces what's already built (funding, the
configured trading mode, trades, backtests) but currently invisible in the UI.

## Goal

The dashboard today shows live portfolio *state* (account KPIs, equity curve, positions with
side/leverage/liq price, decisions, sentiment) but four things are missing: **funding is
invisible** (it only bleeds equity), the bot's **configured mode is never shown** (the UI never
reads config), **trades aren't listed** (only counted), and **backtest results have no in-app
view** (CLI → CSV only). This sub-project closes those four gaps so the paper-trading experience
is complete and observable.

It is **read-only display plus two small engine writes**. No new trading behavior; the risk gate,
fills, funding mechanics, and liquidation are untouched.

## Architecture / data flow

The dashboard reads snapshot files from `data/` every 5s through the resilient `readOr` helper
(missing/unreadable file → fallback, never throws). Two gaps need data the engine has but doesn't
expose, so the engine gains a small accumulator and one new snapshot file; the other two surfaces
read files that already exist.

```
engine (bot)                         data/                    dashboard (read-only)
  state.funding_accrued  ─persist──>  state.json   ─readOr──>  (funding accrued)
  state.write_status(cfg, state) ──>  status.json  ─readOr──>  StatusStrip + funding
  (existing) append_trade        ──>  trades.csv   ─readOr──>  TradesTable
  (existing CLI) backtest._write_equity ─> backtest_equity.csv ─readOr─> BacktestChart
```

## Engine changes (`engine/state.py`, `engine/bot.py`)

### 1. Cumulative funding accumulator
- `State.funding_accrued: float = 0.0` — a **signed** running total of net funding
  (negative = net paid out, positive = net received). Persisted in `state.json` exactly like
  `last_funding_ts` (load via `raw.get("funding_accrued", 0.0)`; written into the save payload;
  an old snapshot without the key loads as `0.0`).
- In `bot.py`, where funding is applied (the existing `pay = broker.funding_payment(...)` /
  `st.cash = max(0.0, st.cash + pay)` block), also `st.funding_accrued += pay`. One line; gated by
  the same `funding_due and pos.qty != 0` condition, so it only changes when funding actually
  charges. (Funding off ⇒ `funding_accrued` stays `0.0`.)

### 2. Resolved status snapshot
- `state.write_status(snapshot: dict, data_dir: str)` — atomic write to `data/status.json`
  (temp file + `os.replace`), mirroring the existing `write_sentiment`.
- `bot.run_once` builds the snapshot from the **resolved** config and current state, and writes it
  once per cycle wrapped in try/except (advisory — a write error never aborts the cycle, same as
  the sentiment write). It is written **unconditionally at the end of the cycle** (not gated on
  `prices`) so the UI always reflects the current mode even if every symbol was skipped. By the
  time it's written, `cfg.risk.allow_short` is already the resolved bool (the bot resolves it right
  after `make_exchange`) and `cfg.risk.leverage` is the load-time-clamped value.
- **Shape** (`status.json`):
  ```json
  {
    "ts": "2026-06-28T10:00:00+00:00",
    "strategy": "hybrid",
    "exchange": "binance",
    "risk": {
      "allow_short": false,
      "leverage": 1.0,
      "maintenance_margin_pct": 0.005,
      "funding_rate": 0.0,
      "funding_interval_hours": 8.0,
      "max_position_pct": 0.25,
      "stop_loss_pct": 0.05
    },
    "funding": { "accrued": 0.0, "last_funding_ts": null }
  }
  ```

No backtest-side change: `funding_accrued` is a live-bot accumulator; the backtest already folds
funding into its equity curve (slice 3).

## Dashboard changes (`desktop/`)

### Parsing + plumbing
- `src/lib/parse.ts`:
  - `Status` type mirroring `status.json` (with a nested `risk` and `funding`).
  - `BacktestPoint = { ts: string; equity: number; buyHold: number }` and
    `parseBacktestCsv(text) -> BacktestPoint[]` — parses the `ts,equity,buy_hold` CSV the backtest
    CLI writes (header row + a baseline row with an empty `ts` + data rows). Empty/header-only → `[]`.
  - `Snapshot` widens to `{ ..., status: Status | null, backtest: BacktestPoint[] }`.
- `src/lib/snapshot.ts` `readSnapshot`: two more `readOr` reads — `status.json` → `Status | null`
  (`JSON.parse`), and `backtest_equity.csv` → `BacktestPoint[]` (`parseBacktestCsv`). Both fall back
  to null/`[]` when absent.
- `src/lib/status.ts` (new) — pure formatters, unit-tested:
  - `leverageMode(lev?: number) -> string` — `"1× (off)"` for `1`, else `"5×"`.
  - `shortingLabel(allow?: boolean) -> string` — `"on"` / `"off"`.
  - `fundingSummary(status: Status | null) -> string` — `"off"` when rate is 0, else
    `"0.010%/8h"` (rate as a percentage of notional, interval hours).
  - `accruedLabel(accrued?: number) -> string` — `"+$0.80 received"` / `"−$1.23 paid"` / `"$0.00"`.

### Components
- `StatusStrip.tsx` (new) — a card under the title rendering mode chips from `snapshot.status`:
  Strategy · Exchange · Leverage (`leverageMode`) · Shorting (`shortingLabel`) · Funding
  (`fundingSummary` + `accruedLabel` for cumulative) · Max position (`max_position_pct`) · Stop
  (`stop_loss_pct`). Null status → a muted "waiting for the bot to write status…" line.
- `TradesTable.tsx` (new) — lists `snapshot.trades` (time · symbol · side · qty · price · fee);
  empty → "No fills yet." Newest first (reverse).
- `BacktestChart.tsx` (new) — a recharts line/area chart of `snapshot.backtest` (strategy `equity`
  vs `buyHold`), mirroring `EquityChart`'s styling; empty → "Run a backtest (`python -m
  engine.backtest …`) to see results here."
- `App.tsx` — render `StatusStrip` directly under the sub-title; add a **Trades** card and a
  **Backtest** card to the existing grid; update the `EMPTY` constant to
  `{ ..., status: null, backtest: [] }`.
- `assets`/CSS — chip styling for the status strip (reuse existing card/table classes where
  possible).

## Testing

- **Engine** (`tests/test_state.py`, `tests/test_bot.py`):
  - `funding_accrued` round-trips through save/load; absent key → `0.0`.
  - With funding on and due, a cycle increments `funding_accrued` by the signed payment (long ⇒
    negative, short ⇒ positive); funding off ⇒ stays `0.0`.
  - `write_status` writes atomic JSON (temp cleaned up); the bot writes `status.json` each cycle with
    the **resolved** `allow_short` (a `None`-auto config that resolves to a bool appears as the bool)
    and the funding summary; a status-write error doesn't abort the cycle.
- **Desktop** (vitest, `src/lib/**`):
  - `parseBacktestCsv`: header+baseline+rows → points; empty/header-only → `[]`; baseline row's
    empty `ts` handled.
  - `leverageMode` / `shortingLabel` / `fundingSummary` / `accruedLabel` band/format cases
    (including the `1×` off case, rate 0 → "off", negative accrued → "paid").
  - `readSnapshot` resilience: missing `status.json`/`backtest_equity.csv` → `null`/`[]`.
- **Visual** (Playwright, built renderer + representative snapshot at 1280 / 768 / 375): status
  strip renders the mode chips + cumulative funding; trades and backtest cards render with data and
  in their empty states; mobile reflow holds; no console errors beyond the favicon 404.

## Files

| file | change |
|---|---|
| `engine/state.py` | `State.funding_accrued` (persist); `+ write_status` (atomic) |
| `engine/bot.py` | accumulate `funding_accrued` on funding; build + write `status.json` each cycle |
| `desktop/src/lib/parse.ts` | `Status` type, `BacktestPoint`, `parseBacktestCsv`, widen `Snapshot` |
| `desktop/src/lib/snapshot.ts` | read `status.json` + `backtest_equity.csv` |
| `desktop/src/lib/status.ts` (new) | `leverageMode` / `shortingLabel` / `fundingSummary` / `accruedLabel` |
| `desktop/src/renderer/src/components/StatusStrip.tsx` (new) | mode + funding chips |
| `desktop/src/renderer/src/components/TradesTable.tsx` (new) | recent fills |
| `desktop/src/renderer/src/components/BacktestChart.tsx` (new) | backtest equity vs buy-hold |
| `desktop/src/renderer/src/App.tsx` | render the strip + 2 cards; update `EMPTY` |
| desktop CSS | status-strip chip styling |
| tests (`test_state`, `test_bot`, desktop `parse`/`status`/`snapshot`) | as above |
| `README.md` | note the dashboard now shows mode, funding, trades, and backtests |

No new dependencies (recharts already used). No change to the gate/fills/funding mechanics or to
`models`/`broker`/`indicators`/`strategies`/`sentiment`/`market`/`llm`/`backtest`.
