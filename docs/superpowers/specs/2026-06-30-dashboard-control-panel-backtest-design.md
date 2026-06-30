# Dashboard Control Panel — Phase 1: Run Backtest — design

**Status:** proposed 2026-06-30
**Branch:** `feat/dashboard-control-panel` off `main` (1122701).
**Source:** user request — the Backtest tab (and the whole dashboard) is a read-only viewer; it shows results but can't *run* anything. User approved turning the dashboard into a **local control panel** that launches the engine.

## Goal

Let the dashboard **launch the engine** from the UI, starting with the Backtest tab: a small form (Since / Until) + a **Run backtest** button that spawns `python -m engine.backtest`, after which the existing chart fills from the engine's CSV output.

This Phase 1 also builds the **reusable spawn foundation** that Phase 2 (a "Run now" button + the scheduler) will sit on.

## Architecture

The Electron **main process** (Node) gains the ability to spawn the Python engine via `child_process.spawn`. The renderer asks for it over IPC; the engine writes its output file; the dashboard's existing 5 s poll picks the file up.

```
[Backtest form] --runBacktest(opts)--> preload --invoke("run-backtest")-->
  main: runBacktest(opts)
    repoRoot = resolve(dataDir(), "..")          # dev: parent of data/ = repo root
    python   = repoRoot/.venv/bin/python || "python3"
    spawn(python, buildBacktestArgs(opts), { cwd: repoRoot, env: envWithoutLiveArm })
    -> resolves { ok, code, stderrTail } on process 'close'
  -> writes data/backtest_equity.csv
  -> renderer's 5s poll -> parseBacktestCsv -> BacktestChart fills
```

## Decisions (locked unless vetoed)

### Spawn foundation (main process)
- **`desktop/src/lib/backtest.ts`** (NEW, pure, unit-tested): `buildBacktestArgs(opts) -> string[]`.
  - `opts: { since: string; until?: string }`.
  - Returns `["-m", "engine.backtest", "--since", opts.since, ...(opts.until ? ["--until", opts.until] : []), "--out", "data/backtest_equity.csv"]`.
  - Symbols / strategy / capital are intentionally omitted in v1 — the engine defaults them from `config.yaml`.
  - A second pure helper `isIsoDate(s) -> boolean` (`/^\d{4}-\d{2}-\d{2}$/`) validates `since` before spawning.
- **`desktop/src/main/engine.ts`** (NEW): `runBacktest(opts): Promise<{ ok: boolean; code: number | null; stderrTail: string }>`.
  - `repoRoot = resolve(dataDir(), "..")` (reuses `dataDir()` from `../lib/snapshot`).
  - `python` = `repoRoot/.venv/bin/python` if it exists (`fs.existsSync`), else `"python3"`.
  - Reject (`ok:false`) early if `!isIsoDate(opts.since)` — no spawn.
  - `const env = { ...process.env }; delete env.LIVE_TRADING_ARMED;` — **defense in depth: a dashboard-launched process can never arm live.** (Backtest places no orders regardless.)
  - `spawn(python, buildBacktestArgs(opts), { cwd: repoRoot, env })`; collect stderr (cap the tail at ~2 KB); resolve `{ ok: code === 0, code, stderrTail }` on `'close'`. On spawn `'error'` (e.g. python missing) resolve `{ ok:false, code:null, stderrTail: <message> }`.
  - `# ponytail: dev-local repoRoot/venv resolution; packaged-app python bundling is the deferred C1, out of scope.`
- **`desktop/src/main/index.ts`**: add `ipcMain.handle("run-backtest", (_e, opts) => runBacktest(opts))` inside `whenReady` (beside the existing `snapshot` / `set-mode` handlers).
- **`desktop/src/preload/index.ts`**: add `runBacktest: (opts) => ipcRenderer.invoke("run-backtest", opts)` to the exposed `api`.

### Backtest form (renderer)
- **`desktop/src/renderer/src/components/BacktestForm.tsx`** (NEW): controlled inputs **Since** (`<input type="date">`, required) and **Until** (`<input type="date">`, optional), plus a **Run backtest** button.
  - Local state: `since`, `until`, `running`, `result` (`null | { ok; stderrTail }`).
  - Submit: button disabled when `!since || running`; on click set `running`, `await window.api.runBacktest({ since, until: until || undefined })`, then clear `running` and store `result`.
  - On `ok`: show "Backtest complete — chart updating…" (the App's 5 s poll refreshes `snap.backtest`; no manual refetch needed). On failure: show "Backtest failed" + the `stderrTail` in a `<pre>`.
  - Uses native `<input type="date">` (no date-picker dependency — ponytail).
- **`desktop/src/renderer/src/App.tsx`** backtest view: render `<BacktestForm />` above the existing `<BacktestChart points={snap.backtest} />` inside the Backtest card.
- **`desktop/src/renderer/src/index.css`**: minimal `.bt-form` layout (row of label+input, a primary button reusing the existing accent), `.bt-result` / error `<pre>` styling.

### Safety / scope
- **No change to the live-trading safety model.** Backtest never places orders. The spawn env strips `LIVE_TRADING_ARMED`, so even Phase 2's "run the bot" controls (same foundation) can only ever paper/shadow — live stays operator-only via CLI/env. `create_order` and the two-switch gate are untouched.
- Dev-local only: `repoRoot`/venv are derived from `dataDir()`'s parent. Packaged-app python resolution is out of scope (deferred C1).

## Data flow
1. User picks Since (+ optional Until), clicks Run.
2. `runBacktest` spawns the engine with `cwd = repoRoot`; engine fetches OHLCV, simulates, writes `data/backtest_equity.csv`.
3. IPC resolves `{ ok, code, stderrTail }`; the form shows the outcome.
4. The App's 5 s `getSnapshot` poll re-reads `backtest_equity.csv` → `BacktestChart` renders the equity vs buy-hold curve.

## Error handling
- Invalid `since` (not `YYYY-MM-DD`) → rejected in `runBacktest` before spawn, `ok:false`.
- python/engine failure (bad date range, no network, exchange error) → non-zero exit; the form surfaces `stderrTail`. No partial CSV is required — `parseBacktestCsv` already tolerates a missing/empty file (returns `[]`).
- Spawn `'error'` (python not found) → `ok:false` with the message.

## Testing
- **vitest (`src/lib`):** `buildBacktestArgs` (since-only; since+until; verifies `--out` and arg order) and `isIsoDate` (valid / invalid / empty).
- **Playwright (1280/768/375):** Backtest form renders; Run disabled until Since set; clicking Run (with `window.api.runBacktest` stubbed) shows the running → result states; an error result renders the stderr `<pre>`.
- **Build:** `npm run build` exit 0 (main-process `engine.ts` compiles).
- **Manual (dev):** with the venv present, run a real backtest from the UI (e.g. Since = 90 days ago) → CSV written → chart fills. The main-process spawn has no unit test; it is build- + manually-verified.

## Out of scope (Phase 2, same foundation)
- "Run now" button (spawn `python -m engine.bot` once).
- **Scheduler** — main-process interval timer running the bot every `interval_seconds`, configured from an in-app settings page (the user's original ask).
- Advanced backtest fields (symbols / strategy / capital / timeframe).
- Packaged-app python/venv bundling (deferred C1).
