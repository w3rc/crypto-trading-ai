# Dashboard Control Panel — Phase 2: Run-now + In-app Scheduler — design

**Status:** proposed 2026-06-30
**Branch:** `feat/dashboard-scheduler` off `main` (58fcf6b).
**Source:** user request — after Phase 1 (run backtest from the UI), give the dashboard a **Run now** button and an **in-app scheduler** that runs the bot on a recurring cadence. Builds directly on Phase 1's spawn foundation.

## Goal

Let the dashboard run the trading bot on demand and on a schedule, all from a new **Settings** view:
- **Run now** — spawn one `python -m engine.bot` cycle.
- **Scheduler** — an Electron main-process `setInterval` that spawns the bot every N seconds *while the app is open*, configured by an on/off toggle + interval and persisted to `data/scheduler.json`.

## Architecture

Phase 1 shipped `runBacktest` spawning `python -m engine.backtest` via the main process, with `pinnedEnv` (pins `LIVE_TRADING_ARMED="no"`). Phase 2:
- Extracts a shared private `spawnEngine(args)` in `engine.ts`; `runBacktest` and the new `runBot` both call it (DRY — both inherit the same safety).
- Adds a main-process **scheduler manager** (`main/scheduler.ts`) that owns a single `setInterval` and (re)arms it from a `Schedule` config.
- The renderer **Settings view** reads/writes the schedule over IPC; saving re-arms the timer. The existing 5 s snapshot poll surfaces each run's results; the sidebar's "updated Xs ago" already shows liveness.

In-app model (user-chosen): the timer runs only while the dashboard is open — closing the app pauses the schedule. No OS cron, no permissions, cross-platform.

## Decisions (locked unless vetoed)

### Spawn foundation (engine.ts)
- Extract `function spawnEngine(args: string[]): Promise<RunResult>` — the existing pinnedEnv + cwd=repoRoot + stderr-tail + close/error logic, parameterised on argv.
- `runBacktest(opts)` = validate `since` then `spawnEngine(buildBacktestArgs(opts))` (external behavior unchanged).
- `runBot(): Promise<RunResult>` = `spawnEngine(["-m", "engine.bot"])` — no args; the bot reads `config.yaml` + `control.json` (mode) itself.
- **Safety unchanged:** every spawn goes through `pinnedEnv`, so a Run-now or scheduled run can never arm live — in any mode (`live`-without-arm shadows). `bot.lock` (`acquire_lock`) makes a scheduled run overlapping a manual one safe (the second exits cleanly).

### Scheduler config (src/lib/scheduler.ts — pure + fs, mirrors control.ts)
- `type Schedule = { enabled: boolean; intervalSeconds: number }`. `DEFAULT_SCHEDULE = { enabled: false, intervalSeconds: 900 }` (default **off** — opt-in).
- `clampInterval(n): number` = `Math.min(86400, Math.max(60, (isFinite(n) && Math.round(n)) || 900))` — floor 60 s / cap 1 day so you can't hammer the LLM/credits, and a huge value can't overflow `setInterval`'s `TIMEOUT_MAX` (~24.8 days) into a 1 ms tick; non-finite/0/Infinity → 900. (pure, unit-tested)
- `parseSchedule(raw: unknown): Schedule` — coerce a parsed-JSON value to a valid `Schedule` (boolean `enabled`, clamped `intervalSeconds`), falling back to defaults for missing/garbage fields. (pure, unit-tested)
- `readSchedule(dir): Promise<Schedule>` — read `scheduler.json` → `parseSchedule`; missing/corrupt → `DEFAULT_SCHEDULE`. `writeSchedule(dir, s): Promise<Schedule>` — clamp + write `scheduler.json`, returns the clamped value. (fs, mirrors control.ts; build-verified)

### Scheduler manager (main/scheduler.ts)
- Module-level `handle: NodeJS.Timeout | null` + `inFlight: boolean`.
- `applySchedule(s: Schedule)`: clear any existing interval; if `s.enabled`, `setInterval` every `s.intervalSeconds * 1000` ms, each tick — skip if `inFlight` (avoid pile-up; `bot.lock` is the real guard), else set `inFlight`, `await runBot()`, clear `inFlight` in `finally`.
- Called once on startup (`readSchedule → applySchedule`) and on every `set-schedule`. (build-verified — timers + spawn aren't unit-tested)

### IPC + preload
- `main/index.ts` (inside `whenReady`, beside the existing handlers): `run-bot` → `runBot()`; `get-schedule` → `readSchedule(dataDir())`; `set-schedule` → `writeSchedule(dataDir(), s)` then `applySchedule(saved)`, return `saved`. On startup: `readSchedule(dataDir()).then(applySchedule)`.
- `preload/index.ts`: expose `runBot()`, `getSchedule()`, `setSchedule(s)`.

### Settings view (renderer)
- New nav item `{ id: "settings", label: "Settings" }` (added to `View` + `NAV` in `Sidebar.tsx`); `App.tsx` renders `<Settings />` in a card when `view === "settings"`.
- `components/Settings.tsx`: on mount `getSchedule()` → populate a controlled **enabled** checkbox + **interval (s)** number input; **Save** calls `setSchedule({enabled, intervalSeconds})` and stores the returned clamped value; a one-line summary ("Scheduler on — every 900s" / "off"). A **Run now** button spawns one cycle with running/result/error states (same pattern as the backtest form). A short note that the schedule runs only while the app is open and that interval should stay near `config.interval_seconds` for accurate freshness.
- `index.css`: a small `.settings-form` block (reuse the `.bt-form` input/button styling family).
- `.gitignore`: add `data/scheduler.json` (runtime file, like `control.json`).

## Data flow
1. Settings page → `set-schedule` IPC → main writes `scheduler.json` + `applySchedule` re-arms the timer.
2. Each tick (or Run now) → `spawnEngine(["-m","engine.bot"])` → bot reads `control.json` mode, runs a cycle, writes `state/status/decisions`.
3. The 5 s `getSnapshot` poll refreshes the dashboard; the sidebar freshness shows "updated Xs ago".

## Error handling
- A failed bot run (non-zero exit / spawn error) resolves `{ ok:false, stderrTail }`; Run-now surfaces it. A scheduled tick that fails is swallowed by the manager's `finally` (logged via the engine's own output) and the next tick proceeds — one bad cycle doesn't stop the schedule.
- Corrupt/missing `scheduler.json` → `DEFAULT_SCHEDULE` (off). Invalid interval from the form → clamped.

## Testing
- **vitest (`src/lib`):** `clampInterval` (floor 60, rounds, 0/NaN→900); `parseSchedule` (valid; missing fields→defaults; garbage→defaults; interval clamped).
- **build:** `npm run build` exit 0 (main `scheduler.ts` + `engine.runBot` compile).
- **Playwright (1280/768/375):** Settings nav + view render; `getSchedule` populates the form (stubbed); toggling enabled + Save calls `setSchedule`; **Run now** shows running → result (stubbed `runBot`); error result renders.
- **manual (dev):** enable the scheduler at a short interval, confirm the bot runs a cycle (paper, safe) and the dashboard refreshes; toggle off → stops.

## Safety / scope
- **No change to the live-trading safety model.** Every dashboard-spawned process goes through `pinnedEnv` (`LIVE_TRADING_ARMED="no"`), so neither Run-now nor the scheduler can place a real order, in any mode. `create_order`, the two-switch arm, and `control.json`-based mode selection are untouched. Arming live remains operator-only (CLI/env + real key), which the dashboard never sets.
- Dev-local (repoRoot/venv from `dataDir()`'s parent — inherited from Phase 1). Packaged-app python bundling still out of scope.

## Out of scope
- OS-level cron/systemd (the user chose the in-app timer).
- Advanced schedule (cron expressions, per-symbol, time windows) — just on/off + interval.
- Surfacing a precise "next run in Xs" countdown from the main timer — the sidebar freshness already conveys liveness; revisit only if the schedule cadence proves hard to read.
