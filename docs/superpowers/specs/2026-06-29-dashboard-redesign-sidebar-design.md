# Dashboard UX Redesign — Nav Sidebar (design)

**Status:** approved 2026-06-29
**Scope:** Pure presentation redesign of the Electron dashboard renderer. **No engine changes** — `data/status.json` already carries `mode`, `halted`, `risk`, `funding`, and the existing snapshot files supply everything. Keeps the current dark-glass palette, fonts, and chart/table/sentiment component internals; restructures layout, hierarchy, and the safety-state treatment.

## Problem

The current dashboard is a flat scroll of eight identical glass cards with no hierarchy. The most important live-bot state — **is it LIVE, is it HALTED, what's my P&L** — has the same visual weight as reference params (max position, stop). `MODE: LIVE` is plain text; `HALTED: YES` is a small grey chip among nine identical chips. The title hardcodes "Paper-Trading" even in live mode. Wide screens are underused (1100px cap, 2-col grid) and the grid leaves orphan/empty cells.

## Goal

A nav-sidebar layout that (1) **pins the safety-critical status** (mode + halted, color-coded) so it is visible on every view, (2) gives the dashboard real hierarchy via section views, and (3) uses the full width. App-like, not a card dump.

## Architecture

Split the renderer into a **fixed left rail + a main view area**. A single `useState` in `App.tsx` tracks the active section; the rail's nav links swap the main view. No router.

```
view = "overview" | "positions" | "activity" | "sentiment" | "backtest"   (default: "overview")
```

```
┌─────────────┬────────────────────────────────────┐
│  ● LIVE     │  <active view fills the main area>   │
│  Crypto Bot │                                     │
│  $2533 +$133│   Overview:  account + equity curve  │
│ ─────────── │              + positions + risk      │
│ ▸ Overview  │   Positions: positions table         │
│   Positions │   Activity:  decisions + trades       │
│   Activity  │   Sentiment: sentiment panel          │
│   Sentiment │   Backtest:  backtest chart           │
│   Backtest  │                                     │
│ ─────────── │                                     │
│ binance·5s  │                                     │
└─────────────┴────────────────────────────────────┘
```

## Components / files

- **New `Sidebar.tsx`** — the fixed rail. Props: `status: Status | null`, `state: State | null` (for equity/P&L), `view: View`, `onNavigate: (v: View) => void`.
  - Brand: "Crypto Trading Bot" (drops "Paper-Trading").
  - **Status block, color-coded** (the safety anchor): mode dot + word. PAPER neutral · SHADOW blue · LIVE amber · `halted` overrides to **red** with `■ HALTED`. Always visible.
  - **Pinned equity + P&L** (P&L color-coded up/down) directly under the status.
  - **Nav links** for the five views, active one highlighted.
  - **Footer:** `exchange · strategy · read-only · polls 5s`.
- **`App.tsx`** — restructured into `<Sidebar/> + <main>`; holds the `view` state and the existing 5s `getSnapshot` poll (unchanged); renders the active view. Account-KPI markup + the per-view composition live here (or in tiny per-view wrappers).
- **`index.css`** — rail + main grid; new mode-color CSS vars (`--mode-live`, `--mode-shadow`, `--mode-paper`, `--halted`); responsive breakpoint; retire/replace the old `.wrap`/`.grid`/`.chips` headline usage as needed (keep `.chip` styles where the risk card reuses them).
- **`lib/status.ts`** — add `modeBadge(mode?: string, halted?: boolean) -> { label: string; tone: "live" | "shadow" | "paper" | "halted" }`. Pure, **unit-tested** (vitest covers `lib/`). `halted` true ⇒ tone `"halted"` regardless of mode; else map mode → tone (default `paper`).
- **Retire `StatusStrip.tsx`** — its content splits into the rail status block + the Overview **Risk** card. (Remove the component and its import.)
- **Reused unchanged:** `EquityChart`, `PositionsTable`, `TradesTable`, `DecisionLog`, `SentimentPanel`, `BacktestChart` (internals untouched; `DecisionLog` gets the small clarity tweak below).

## Views

- **Overview** (default): account KPIs (equity / cash / P&L, P&L color-coded) + equity curve + open positions + a compact **Risk** card (leverage, shorting, funding, max-position, stop, maintenance-margin — demoted to reference, reusing `.chip` styling).
- **Positions:** the full positions table.
- **Activity:** Decisions + Trades side-by-side on wide, stacked on narrow.
- **Sentiment:** the sentiment panel.
- **Backtest:** the backtest chart.

## Clarity fixes

- **Honest title:** "Crypto Trading Bot"; mode lives in the rail status block, not the title.
- **Decisions cue:** replace the cryptic `hold*` + "(* = not executed)" legend with an explicit **Executed** indicator (a ✓ for executed, a muted "skipped" tag otherwise). `DecisionLog` only.
- **Risk params demoted** from headline chips to the Overview Risk card.

## Color semantics

New CSS vars + `modeBadge` tone → class:
- `paper` → muted/neutral (calm; simulated)
- `shadow` → blue (real reads, zero execution)
- `live` → amber (real money active — caution)
- `halted` → red (execution stopped) — overrides mode tone whenever `status.halted` is true.

P&L keeps existing `--up`/`--down`.

## Responsive

- **Desktop (>820px):** rail ~240px fixed left; main fills the remaining width (no 1100px cap on the content area).
- **Tablet/mobile (≤820px, verified at 375):** rail collapses to a **top bar** — status block + a horizontal, scrollable nav row above the main view. No hamburger/drawer (YAGNI for five links).

## Out of scope

Engine/data changes; new panels or metrics; theming/palette changes (kept); routing libraries; persisting the selected view across reloads.

## Testing

- **Unit (vitest, `lib/`):** `modeBadge` — paper/shadow/live tone mapping, and `halted` overriding to `"halted"` for every mode.
- **Build:** `npm run build` exit 0 (tsc + electron-vite type-check the components).
- **Playwright (1280 / 768 / 375):** render the real `App` via a harness stubbing `window.api.getSnapshot`, across **paper / live / halted** statuses and at least the **Overview**, **Activity**, and one more view — confirm: rail status color per mode, the red HALTED treatment, pinned equity/P&L, nav switching the view, and the responsive top-bar collapse at 375. Clean up harness artifacts after.
