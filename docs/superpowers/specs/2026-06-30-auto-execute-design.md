# Auto-Execute (manual approve / auto place) — design

**Status:** proposed 2026-06-30
**Branch:** `feat/auto-execute` off `main` (56dc81d).
**Source:** user request — "add an option to auto place trades; if it's disabled the user places trades manually." Scope locked (earlier AskUserQuestion): applies to **paper + live (if armed)**; a manual Execute may place a real order in live, still gated by the two-switch arm. Default state locked: **OFF (manual by default).**

## Goal

Add an **auto-execute** toggle. When ON, the bot decides and trades automatically (today's behavior). When OFF — the **default** — the bot only *proposes*: each non-hold decision becomes a **pending suggestion** the user manually **Executes** or **Dismisses** from the dashboard. Manual Execute runs through the same execution path as the auto-cycle (no second path to `create_order`); in live mode it can place a real order, still fully gated by `mode:live` + `LIVE_TRADING_ARMED=yes` + no `data/HALT`.

This is the project's largest safety change: it is the first dashboard → live-order path. It reuses the existing two-switch arm and the single `create_order` gate rather than adding a parallel execution path.

## Architecture (Approach A — single execution path)

The bot's cycle, when auto-execute is off, writes each non-hold decision to `data/pending.json` instead of executing. Clicking **Execute** spawns `python -m engine.execute SYMBOL`, which calls the **same** `run_once` — scoped to one symbol, with the stored decision **forced** in place of the strategy call. Auto-trades and manual-trades therefore share one tested path to `create_order`; a fix to the HALT check / clamp / sidecar applies to both automatically, and `create_order` keeps exactly one caller (`_run_live`).

```
auto-execute OFF, scheduled/Run-now cycle (pinnedEnv arm="no"):
  run_once → paper: defer; live→shadow: defer  → writes data/pending.json (suggestions, no orders)
  dashboard polls snapshot → Pending panel (Overview) shows suggestions

user clicks Execute on ETH/USDT:
  IPC execute-suggestion → engine.ts executeSuggestion → spawnEngineArmed (the ONE un-pinned spawn)
  → python -m engine.execute "ETH/USDT"
    → mode guard (shadow→exit2, live&!armed→exit3, no pending→exit4)
    → run_once(only_symbol="ETH/USDT", forced_decision=stored)
      → paper: apply_fill   |   live & armed: HALT-check → clamp → create_order → sidecar
      → _apply_pending clears that entry
  → snapshot poll reflects the trade; pending entry gone
```

### The safety property that falls out

`spawnEngine` pins `LIVE_TRADING_ARMED="no"` on **every** spawn (scheduler, Run-now, backtest). So the auto-scheduler can **never** auto-place a live order from the dashboard — live mode there routes to `_run_shadow` (suggestions only). `engine.execute` is the **one** un-pinned spawn (`spawnEngineArmed`), inheriting the operator's real arm. Net:

> From the dashboard, a real live order can happen **only** via an explicit Execute click (with a confirm), and only if the app was launched in an armed environment (`LIVE_TRADING_ARMED=yes` / `.env`). The auto-scheduler stays pinned-unarmed regardless of the flag. The engine enforces the arm itself, so an unarmed app fails closed with a clear message — Execute never silently no-ops.

## Components

### Engine

**`engine/config.py`**
- `Config.auto_execute: bool = False` field.
- `_auto_execute_override(data_dir, default: bool) -> bool` — twin of `_mode_override`: reads `data/control.json`'s `auto_execute`; returns it **only if it is a bool**, else `default`. Fail-safe on missing/corrupt/non-dict.
- In `load_config`: `auto_execute=_auto_execute_override(raw["data_dir"], bool(raw.get("auto_execute", False)))`.
- `config.yaml` gains `auto_execute: false` (optional; code default is already `False`).

**`engine/state.py`** — pending I/O (mirrors the existing JSON helpers, atomic write like `save_state_atomic`):
- `load_pending(data_dir) -> dict` — read `data/pending.json`; `{}` on missing/corrupt/non-dict.
- `save_pending(pending: dict, data_dir) -> None` — atomic write.

**`engine/bot.py`**
- `_apply_pending(pending, sym, order, decision, price, ts, deferred)` — the single shared rule:
  - `if deferred and order is not None:` `pending[sym] = {"ts": ts, "action": order.side, "size": decision.size, "reason": decision.reason, "price": price}`
  - `else:` `pending.pop(sym, None)`
- `run_once(cfg=None, market=None, strategy=None, only_symbol=None, forced_decision=None)`:
  - paper block (and `_run_live`): at cycle start `pending = state_mod.load_pending(cfg.data_dir)`; per symbol skip if `only_symbol and sym != only_symbol`.
  - Decision selection order (safety first): `force_close` → else `forced_decision` (if not None) → else `strategy(...)`.
  - `deferred = forced_decision is None and not cfg.auto_execute`. When `deferred`: `append_decision(executed=False)`, `_apply_pending(..., deferred=True)`, `continue` (no fill). When not deferred: execute as today, then `_apply_pending(..., deferred=False)` (clears the entry).
  - At cycle end `state_mod.save_pending(pending, cfg.data_dir)`.
- `_run_shadow(cfg, market, strategy)` — same pending rule (`forced_decision` never reaches shadow; `engine.execute` guards it out). Under auto-OFF it defers (writes pending so the live-manual workflow has suggestions); under auto-ON it clears.
- `_status_payload` adds `"auto_execute": cfg.auto_execute` (after `"armed"`).

**`engine/execute.py`** (new) — `python -m engine.execute "ETH/USDT"`:
1. `load_dotenv()`; `cfg = load_config()`.
2. Mode guard: `cfg.mode == "shadow"` → print + exit **2**; `cfg.mode == "live" and not _live_armed()` → print + exit **3**; `pending.get(symbol)` missing → print + exit **4**; missing argv → exit **1**.
3. Build `Decision(action=p["action"], size=float(p.get("size", 1.0)), reason=p.get("reason", ""))` and call `run_once(cfg=cfg, only_symbol=symbol, forced_decision=decision)`. `forced_decision` skips the strategy call (no re-decide, no LLM spend) and bypasses the defer branch, so it executes through the same code; `_apply_pending(deferred=False)` clears the entry. Exit **0**.

Edge: a forced decision that `plan_order` reduces to no order (e.g. insufficient cash) → `order is None` → entry cleared, `append_decision(executed=False)` records why; no trade. Acceptable (the Activity log explains it).

### Lib — `desktop/src/lib`

- **`pending.ts`** (new) — `parsePending(raw): Pending` (keep `{symbol: {...}}` shape, drop malformed); `removePending(dir, sym): Promise<Pending>` (read-modify-write `pending.json`, dynamic `import()` of `fs`/`path` like `symbols.ts` so the renderer build stays clean).
- **`control.ts`** — make writers **merge** instead of clobber: `writeControl(dir, mode)` preserves an existing `auto_execute`; new `writeAutoExecute(dir, on: boolean)` preserves an existing `mode`; shared `_merge(dir, patch)` reads the current `control.json`, applies the patch, writes.
- **`snapshot.ts`** — read `pending.json` → `snap.pending` (`{}` fallback).
- **`parse.ts`** — `Pending = Record<string, { ts: string; action: string; size: number; reason: string; price: number }>`; `Snapshot.pending: Pending`; `Status.auto_execute?: boolean`.

### Main — `desktop/src/main/engine.ts`

- Extract the shared spawn body (cwd, python resolution, stderr-tail, close → `RunResult`) into a helper taking `env`, so `spawnEngine` and `spawnEngineArmed` differ by exactly one line — `env: pinnedEnv(process.env)` vs `env: process.env`.
- `spawnEngineArmed(args)` — the un-pinned spawn, with the safety comment block. `executeSuggestion(symbol)` → `spawnEngineArmed(["-m", "engine.execute", symbol])`. `runBot`/`runBacktest` stay on `spawnEngine` (pinned).

### IPC + preload

- `main/index.ts`: `execute-suggestion` (sym → `executeSuggestion`), `dismiss-suggestion` (sym → `removePending(dataDir(), sym)`), `set-auto-execute` (on → `writeAutoExecute(dataDir(), on)`).
- `preload/index.ts`: `executeSuggestion(symbol)`, `dismissSuggestion(symbol)`, `setAutoExecute(on)`.

### Dashboard UI

- **`Settings.tsx`** — an auto-execute toggle near the top, reading `status.auto_execute`, writing `setAutoExecute`. Copy: "Auto-execute trades — when off, the bot only proposes; you Execute/Dismiss each one. In live mode an Execute places a real order." Reflects the saved effective value from `status` on poll.
- **`PendingPanel.tsx`** (new) — rendered on **Overview**, only when `Object.keys(snap.pending).length > 0` (manual suggestions must be unmissable). Each entry: `SYM` · BUY/SELL badge · `size` · `reason` · a short relative age + the suggestion price ("12m ago · @ $1583"), where age = `now − ts` computed inline (no new shared helper needed). **Execute** — when `status?.mode === "live"`, a `confirm("Place a REAL market {SIDE} of {SYM}? This uses real funds.")` gate first; paper executes directly; the run result is shown (incl. a fail-closed "live not armed" from exit 3). **Dismiss** — `dismissSuggestion(sym)`. Both reflect on the next 5 s poll.
- **`App.tsx`** — render `<PendingPanel pending={snap.pending} status={snap.status} />` inside `Overview` (above the KPI row), inside the existing `ErrorBoundary`.

## Data flow

1. Auto-execute OFF (default). The scheduler / Run-now cycle decides per symbol and writes `data/pending.json` (non-hold suggestions); no orders placed.
2. The 5 s poll surfaces suggestions in the Overview Pending panel.
3. User clicks Execute → `engine.execute SYMBOL` runs the stored decision through `run_once` at the live price/balance → paper fill or (live+armed) real order → clears that pending entry.
4. Next poll: the trade appears in Activity/Positions, the pending entry is gone.
5. Toggling auto-execute ON resumes automatic execution; pending drains as symbols are processed.

## Safety / scope

- **Single gated site:** `create_order` stays one function with one caller (`_run_live`); manual execute reaches it through `_run_live`, not a parallel path. Re-verify the grep at merge (`create_order` def + ccxt + log + the one `_run_live` caller; `cancel_order`/`withdraw` = 0).
- **Two-switch arm unchanged:** live execution still requires `mode:live` + `LIVE_TRADING_ARMED=yes` + absence of `data/HALT`. `engine.execute` checks HALT inside `_run_live` (mid-cycle kill still honored for the single order).
- **One un-pinned spawn only:** `spawnEngineArmed` is reachable solely from `execute-suggestion`. `runBot`/`runBacktest` remain pinned, so the auto-scheduler can never place a live order from the dashboard.
- **Fail-safe:** corrupt/missing `pending.json` → `{}`; bad `auto_execute` value → `False`; unarmed live Execute → exit 3, no order, clear UI message.
- **`force_close` priority:** a stop-loss still pre-empts a forced manual decision (safety over stale intent). Rare; documented.
- **No re-decide on Execute:** the stored decision is forced — no extra LLM call, and the click executes what the user approved (not a fresh, possibly contradictory decision).
- `data/pending.json` is gitignored (runtime override, like `control.json` / `symbols.json`).
- **Known race (accepted):** a dashboard Dismiss writing `pending.json` concurrently with a cycle's end-save is last-writer-wins; the next cycle regenerates pending. No money impact (pending is selection metadata, never gates an order).

## Testing

- **pytest:** `_auto_execute_override` (default / valid true+false / non-bool / missing-file / corrupt); `run_once` paper with `auto_execute=False` records pending + appends `executed=False` + places no fill; `_run_live` with `auto_execute=False` records pending + never calls `create_order`; `engine.execute` forced path executes a paper fill (stubbed market — asserts the stored decision is used, not the strategy) and clears pending; the mode guards return exit 2 / 3 / 4; `force_close` pre-empts a `forced_decision`; `_status_payload` carries `auto_execute`; `load_pending`/`save_pending` round-trip + corrupt → `{}`.
- **vitest (`src/lib`):** `parsePending` (keeps valid, drops malformed); `removePending` (removes one key, preserves others, missing file → `{}`); `control.ts` merge (`writeControl` preserves `auto_execute`; `writeAutoExecute` preserves `mode`); `snapshot` parses `pending.json`.
- **Keystone safety test (`engine.test.ts` / `spawn`):** `executeSuggestion` spawns with an env where `LIVE_TRADING_ARMED` is **not** forced to `"no"` (inherits `process.env`), while `runBot` does pin it `"no"`. This guards the carve-out and must fail if anyone routes execute through the pinned spawn.
- **build:** `npm run build` exit 0.
- **Playwright (1280 / 768 / 375):** Settings toggle reflects a stubbed `status.auto_execute` and calls `setAutoExecute`; Pending panel renders from stubbed `snap.pending`; paper Execute calls `executeSuggestion` (no confirm); `status.mode==="live"` Execute triggers the confirm and calls through on accept; Dismiss calls `dismissSuggestion`; panel hidden when `pending` is empty.

## Out of scope

- Bulk "Execute all" / "Dismiss all" (per-suggestion only — YAGNI).
- A staleness cutoff that blocks Execute on old suggestions (age is shown; the user is the gate; Execute always re-prices via `plan_order`).
- A typed/double confirmation beyond the single `confirm()` for live.
- Reporting the app's live-arm status in the UI ahead of time (the engine enforces it and reports failure on Execute; `status.armed` is unreliable here because status is written by pinned spawns).
- Editing a suggestion's size/side before executing (execute-as-proposed only).
