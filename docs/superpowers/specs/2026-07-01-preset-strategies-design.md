# Preset trading strategies + dashboard picker

**Date:** 2026-07-01
**Status:** Approved (design)

## Goal

Add four classic, deterministic trading strategies as selectable presets, and let the
user switch the active strategy live from the dashboard — mirroring the existing Mode
toggle. No restart, applies next cycle.

Builds directly on the existing pluggable-strategy registry
(`2026-06-25-pluggable-strategies-design.md`) and the sidebar Mode toggle
(`2026-06-29-sidebar-mode-toggle-design.md`).

## Non-goals (YAGNI)

- Per-strategy tunable parameters in the UI (strategies read `cfg.rules` already).
- Backtest-across-strategies comparison.
- Strategy-specific stop/exit logic — all presets reuse the global risk stop-loss.
- Shorting variants — presets are long-only spot, consistent with `indicator_rule`.

## 1. Bollinger indicator

`engine/indicators.py` → `compute_indicators` adds three keys derived from the
20-period close:

- `bb_mid`  = SMA(close, 20)
- `bb_upper` = `bb_mid` + 2·σ
- `bb_lower` = `bb_mid` − 2·σ

where σ = rolling 20-period standard deviation of close (`.rolling(20).std()`,
population or sample — use pandas default `ddof=1`; documented in the test).
`MIN_ROWS = 50` already guarantees a full 20-window. All existing keys unchanged.

## 2. Four preset strategies

`engine/strategies.py` — four new pure functions, signature
`(features, position, cash, cfg) -> Decision`, all **long-only spot**. A `sell`
returned with no open position is harmless: `broker.plan_order` yields no order and
it logs as a hold — identical to the existing `indicator_rule`. Buy size =
`cfg.rules.buy_size`; sell = full exit (`size=1.0`).

| id | logic | reason string example |
|---|---|---|
| `ma_cross` | `ma_fast > ma_slow` → buy; `<` → sell; else hold | `ma:golden fast=… slow=…` |
| `macd_cross` | `macd > macd_signal` → buy; `<` → sell; else hold | `macd:bull macd=… sig=…` |
| `rsi_reversion` | `rsi < rules.rsi_buy` → buy; `rsi > rules.rsi_sell` → sell; else hold | `rsi:oversold rsi=…` |
| `bollinger` | `price ≤ bb_lower` → buy; `price ≥ bb_upper` → sell; else hold | `bb:lower price=… lower=…` |

Registered in the existing `STRATEGIES` dict — the registry stays the single source of
truth. Ties (equal values) → hold.

## 3. control.json strategy override

`engine/config.py` — add `_strategy_override(data_dir, default)`, a twin of
`_mode_override`:

- reads `control.json` `strategy`, returns it only if it is a key in
  `strategies.STRATEGIES`, else fail-safe to `default`.
- wired into `load_config`:
  `strategy=_strategy_override(raw["data_dir"], raw.get("strategy", "hybrid"))`.

`config.py` imports `from engine import strategies` (no import cycle: strategies →
llm, models; none import config). `_status_payload` already emits `cfg.strategy`, so
the dashboard already receives the active strategy — no bot.py change needed.

## 4. Dashboard picker

- `desktop/src/lib/control.ts` → `writeStrategy(dir, name)` using the existing `_merge`
  read-modify-write; validates `name` against a known id set, no-ops on invalid.
- IPC `set-strategy` (`desktop/src/main/index.ts`) + `setStrategy`
  (`desktop/src/preload/index.ts`), mirroring `set-mode`.
- `desktop/src/renderer/src/components/Sidebar.tsx` → a **native `<select>`** (7
  options total is too many for a segmented control), seeded from `status.strategy`,
  with the same optimistic-pending pattern and "applies next cycle" hint as Mode. No
  confirm dialog — a strategy swap is paper-safe and still deferred unless auto-execute
  is on. `Status.strategy` is already parsed.
- The renderer holds a small `STRATEGIES` list of `{id, label}` (labels: AI (hybrid),
  Indicator rule, Sentiment rule, MA cross, MACD cross, RSI reversion, Bollinger).
  This duplicates the engine registry the same way `MODES` duplicates the mode strings
  — acceptable, small.

## 5. Data flow

`<select>` → `setStrategy` IPC → `writeStrategy` merges `control.json` → next
`run_once` reads it via `load_config` → the chosen strategy proposes → pending
regenerates. Switching mid-run only changes who proposes next cycle; no pending
cleanup needed (each cycle overwrites pending per symbol).

## 6. Error handling / fail-safes

- Unknown strategy in `control.json` → config falls back to default (never crashes).
- `writeStrategy` invalid name → no-op (control.json unchanged).
- Bollinger requires ≥20 rows; already guaranteed by `MIN_ROWS=50`.
- All presets are pure and deterministic — no network, no LLM, cannot raise on normal
  inputs.

## 7. Testing

- `tests/test_indicators.py`: `bb_upper > bb_mid > bb_lower`; `bb_mid ≈ mean(last 20)`.
- `tests/test_strategies.py`: one buy / one sell / one hold case per new strategy.
- `tests/test_config.py`: `_strategy_override` valid / invalid / missing-file → fallback.
- `desktop/src/lib/control.test.ts`: `writeStrategy` valid write + invalid rejected +
  merge preserves other control.json keys (mode, auto_execute).
- Playwright (final): open dashboard, switch the strategy `<select>`, assert the write
  and that status reflects the change.

## Acceptance criteria

1. `config.yaml`/`control.json` can select any of the 7 strategies; bad values fall
   back safely.
2. Each preset produces the documented buy/sell/hold for representative inputs.
3. Dashboard sidebar shows a strategy dropdown reflecting the live `status.strategy`;
   changing it writes `control.json` and the bot honors it next cycle.
4. Full Python suite green; new dashboard unit tests green; Playwright picker verified.
