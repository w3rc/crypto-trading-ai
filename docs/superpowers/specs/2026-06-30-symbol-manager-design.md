# Symbol Manager — design

**Status:** proposed 2026-06-30
**Branch:** `feat/symbol-manager` off `main` (9eded7a).
**Source:** user request — only BTC/USDT and ETH/USDT are tracked; let the user add/remove trading pairs from the dashboard.

## Goal

Let the user manage the bot's trading pairs from the Settings page. Add a **Symbols** section that edits the pair list; the engine reads it each cycle. Removing a pair that holds an open position is blocked (no orphaned, unmanaged positions).

## Architecture

Mirror the existing **mode override**. The engine already reads `data/control.json` to override the config's `mode` (`_mode_override`). We add the same pattern for symbols: a `data/symbols.json` override (a JSON array of pairs) that wins over `config.yaml`'s `symbols` when present and valid, and fails safe to the config list otherwise. The engine also writes the **effective** symbol list into `status.json` so the dashboard knows what's live. The Settings page edits the list and writes `symbols.json` over IPC.

```
Settings Symbols section --setSymbols(list)--> preload --invoke("set-symbols")-->
  main: writeSymbols(dataDir, list)  (validate + dedupe + write data/symbols.json)
  -> next cycle: load_config -> _symbols_override reads symbols.json (valid+non-empty wins, else config.yaml)
  -> bot loops cfg.symbols; _status_payload writes status.symbols
  -> dashboard poll -> Settings reflects the effective list
```

## Components

### Engine (2 small changes)
- **`engine/config.py`** — add `_symbols_override(data_dir, default: list[str]) -> list[str]` (twin of `_mode_override`): reads `data/symbols.json`; if missing/corrupt/not-a-list → `default`; else keep entries that are strings matching `^[A-Z0-9]+/[A-Z0-9]+$` (add `import re`); return the valid list if non-empty, else `default`. Apply it at the `symbols=` line: `symbols=_symbols_override(raw["data_dir"], list(raw["symbols"]))`.
- **`engine/bot.py`** — `_status_payload` writes `"symbols": cfg.symbols` (after `"interval_seconds"`), so the dashboard sees the effective list.

### Lib — `desktop/src/lib/symbols.ts` (pure + fs, like `control.ts`)
- `validSymbol(s): boolean` — `/^[A-Z0-9]+\/[A-Z0-9]+$/`.
- `parseSymbols(raw: unknown): string[]` — keep strings, trim + uppercase, filter `validSymbol`, dedupe (order-preserving).
- `writeSymbols(dir, symbols): Promise<string[]>` — `parseSymbols` the input; throw if empty (at least one required); `mkdir -p`; write `data/symbols.json`; return the cleaned list.

### Dashboard — Settings "Symbols" section
- `App.tsx` passes `status` + `state` to `<Settings status={snap.status} state={snap.state} />`.
- The section seeds its editable list from `status.symbols` (the effective list) when status first loads. It renders each pair as a chip with an **×** remove button. The remove is **disabled (with a tooltip "close the position first")** when that pair has an open position — `state.positions[sym]?.qty` is non-zero.
- An **add** control: a free-text input, validated + uppercased on add (`validSymbol`); ignores duplicates. (Free-text, not a preset dropdown — the exchange supports many pairs.)
- A **Save symbols** button → `setSymbols(list)`; disabled when the list is empty. On success, store the returned cleaned list. A one-line note: each pair = one more LLM call per cycle; the engine applies it on the next cycle.
- `set-symbols` IPC (`writeSymbols(dataDir(), list)`) + preload `setSymbols(list)`.
- CSS: `.symbol-chips` / `.symbol-chip` (reuse the glass/badge family).

### Types
- `Status` (in `parse.ts`) gains `symbols?: string[]` (optional, backward-compatible with old `status.json`).

## Data flow
1. User edits the pair list in Settings, clicks Save → `set-symbols` writes `data/symbols.json`.
2. Next cycle, `load_config` → `_symbols_override` returns the override list; the bot trades exactly those pairs and writes them into `status.json`.
3. The 5 s poll refreshes; the Settings list and the Decisions/Positions views reflect the new set.

## Safety / scope
- **The symbols override is selection metadata — it never gates trading or touches `create_order`, the mode/arm, or risk.** It only changes *which* pairs the bot considers.
- **No orphaned positions:** the UI blocks removing a pair with an open position. (A pair removed while flat has no position to strand.) Manual edits to `symbols.json` outside the UI are out of scope.
- **Fail-safe:** a missing/corrupt/empty/invalid `symbols.json` → the engine uses `config.yaml`'s `symbols`. An unsupported pair (not on the exchange) just fails *that symbol's* fetch for the cycle (logged, non-fatal) — it doesn't stop the others.
- `data/symbols.json` is gitignored (runtime override, like `control.json`).
- Each added pair increases LLM calls/credits per cycle — surfaced in the UI.

## Testing
- **vitest (`src/lib`):** `validSymbol` (valid `BTC/USDT`; invalid `btcusdt`/`BTC-USDT`/``); `parseSymbols` (uppercases, filters invalid, dedupes, drops non-strings).
- **pytest:** `_symbols_override` (valid override list used; missing/corrupt/empty/non-list/all-invalid → config default); `_status_payload` carries `symbols`.
- **build:** `npm run build` exit 0.
- **Playwright (1280/768/375):** Settings Symbols section renders from a stubbed `status.symbols`; add a valid pair appends a chip; an invalid add is rejected; the × is disabled for a pair whose stubbed `state.positions` qty ≠ 0; Save calls `setSymbols`.

## Out of scope
- A preset/searchable pair picker (free-text for v1).
- Validating a pair against the live exchange before saving (the engine surfaces a bad pair per-cycle).
- Auto-closing or migrating positions on removal (removal is simply blocked while a position is open).
