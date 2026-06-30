# Dashboard Control Panel — Phase 2 (Run-now + Scheduler) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Run-now button and an in-app scheduler that spawns the trading bot on a recurring cadence, configured from a new Settings view.

**Architecture:** Extract a shared `spawnEngine(args)` in the Electron main process (so `runBacktest` and the new `runBot` both inherit `pinnedEnv`); add a main-process scheduler that owns one `setInterval` armed from `data/scheduler.json`; a renderer Settings view reads/writes the schedule over IPC and offers Run-now. The existing 5 s snapshot poll surfaces each run.

**Tech Stack:** Electron + React + TypeScript, electron-vite, vitest (node env, `src/lib/**`). Python 3.14 engine (unchanged). No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-06-30-dashboard-control-panel-scheduler-design.md`

## Global Constraints

- **No new dependencies.** Native inputs + Node built-ins.
- **Safety (highest priority):** every engine spawn goes through `spawnEngine`, which uses `pinnedEnv(process.env)` (pins `LIVE_TRADING_ARMED="no"`). Neither Run-now nor the scheduler may ever arm live — in any mode. NO change to the live-trading safety model, the mode toggle, or `create_order`.
- **vitest covers `src/lib/**` only.** The pure scheduler helpers (`clampInterval`, `parseSchedule`) get unit tests. The main-process `engine.ts`/`scheduler.ts` and the renderer Settings view are verified by `npm run build` + Playwright.
- **Scheduler default OFF** (opt-in). Interval floor **60 s**. Default interval **900 s**.
- **Commit trailers** (every commit; verify with `git log --format="%B" -1 HEAD`, amend if missing):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Desktop commands from `desktop/`: `npm test`, `npm run build`. Do NOT push. (No Python change.)

---

### Task 1: Engine — extract `spawnEngine`, add `runBot` (build-verified)

**Files:**
- Modify: `desktop/src/main/engine.ts`

**Interfaces:**
- Consumes: `pinnedEnv` (`../lib/spawn`), `buildBacktestArgs`/`isIsoDate`/`BacktestOpts` (`../lib/backtest`), `dataDir` (`../lib/snapshot`) — all already imported.
- Produces: `runBot(): Promise<RunResult>` (spawns `python -m engine.bot`). `runBacktest` external behavior unchanged. `RunResult` unchanged.

- [ ] **Step 1: Refactor + add `runBot`**

Replace the body of `desktop/src/main/engine.ts` from the `// ponytail:` comment through the end of `runBacktest` with:

```ts
// ponytail: dev-local repoRoot/venv resolution; packaged-app python bundling (deferred C1) is out of scope.
// Every engine spawn goes through here, so pinnedEnv (LIVE_TRADING_ARMED="no") is applied uniformly.
function spawnEngine(args: string[]): Promise<RunResult> {
  const repoRoot = resolve(dataDir(), "..");
  const env = pinnedEnv(process.env);
  return new Promise((resolveP) => {
    const child = spawn(pythonPath(repoRoot), args, { cwd: repoRoot, env });
    let stderr = "";
    child.stderr.on("data", (d) => { stderr = (stderr + d.toString()).slice(-2048); });
    child.on("error", (e) => resolveP({ ok: false, code: null, stderrTail: e.message }));
    child.on("close", (code) => resolveP({ ok: code === 0, code, stderrTail: stderr.trim() }));
  });
}

export function runBacktest(opts: BacktestOpts): Promise<RunResult> {
  if (!isIsoDate(opts.since)) {
    return Promise.resolve({ ok: false, code: null, stderrTail: `invalid since date: ${opts.since} (expected YYYY-MM-DD)` });
  }
  return spawnEngine(buildBacktestArgs(opts));
}

export function runBot(): Promise<RunResult> {
  return spawnEngine(["-m", "engine.bot"]);
}
```

Leave the imports, `RunResult` type, and `pythonPath` above untouched.

- [ ] **Step 2: Verify the build + existing tests**

Run: `cd desktop && npm test && npm run build`
Expected: vitest green (unchanged count — no lib change); build exit 0. (The backtest arg test and its behavior are unchanged because `runBacktest` still validates `since` and passes `buildBacktestArgs(opts)`.)

- [ ] **Step 3: Commit**

```bash
git add desktop/src/main/engine.ts
git commit -m "refactor(dashboard): extract spawnEngine; add runBot (engine.bot) — shared pinnedEnv"
```

---

### Task 2: Lib — scheduler config (pure helpers + fs)

**Files:**
- Create: `desktop/src/lib/scheduler.ts`
- Test: `desktop/src/lib/scheduler.test.ts`

**Interfaces:**
- Produces:
  - `type Schedule = { enabled: boolean; intervalSeconds: number }`
  - `DEFAULT_SCHEDULE: Schedule` (`{ enabled: false, intervalSeconds: 900 }`)
  - `clampInterval(n: number): number` (floor 60; cap 86400; `Math.round`; 0/NaN/Infinity → 900)
  - `parseSchedule(raw: unknown): Schedule` (coerce/validate, defaults for missing/garbage)
  - `readSchedule(dir: string): Promise<Schedule>` (missing/corrupt → `DEFAULT_SCHEDULE`)
  - `writeSchedule(dir: string, s: Schedule): Promise<Schedule>` (clamps, writes `scheduler.json`, returns clamped)

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/lib/scheduler.test.ts`:

```ts
import { test, expect } from "vitest";
import { clampInterval, parseSchedule } from "./scheduler";

test("clampInterval floors at 60 and rounds", () => {
  expect(clampInterval(900)).toBe(900);
  expect(clampInterval(30)).toBe(60);      // floor
  expect(clampInterval(120.6)).toBe(121);  // rounds
});

test("clampInterval falls back to 900 for 0 / NaN", () => {
  expect(clampInterval(0)).toBe(900);
  expect(clampInterval(NaN)).toBe(900);
});

test("parseSchedule coerces valid input", () => {
  expect(parseSchedule({ enabled: true, intervalSeconds: 300 })).toEqual({ enabled: true, intervalSeconds: 300 });
});

test("parseSchedule defaults missing/garbage fields and clamps", () => {
  expect(parseSchedule({})).toEqual({ enabled: false, intervalSeconds: 900 });
  expect(parseSchedule(null)).toEqual({ enabled: false, intervalSeconds: 900 });
  expect(parseSchedule({ enabled: "yes", intervalSeconds: "x" })).toEqual({ enabled: false, intervalSeconds: 900 });
  expect(parseSchedule({ enabled: true, intervalSeconds: 10 })).toEqual({ enabled: true, intervalSeconds: 60 });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/scheduler.test.ts`
Expected: FAIL — `./scheduler` does not exist.

- [ ] **Step 3: Implement**

Create `desktop/src/lib/scheduler.ts`:

```ts
import { readFile, writeFile, mkdir } from "fs/promises";
import { join } from "path";

export type Schedule = { enabled: boolean; intervalSeconds: number };

export const DEFAULT_SCHEDULE: Schedule = { enabled: false, intervalSeconds: 900 };

export function clampInterval(n: number): number {
  // floor 60s; cap 1 day; 0/NaN/Infinity -> 900 (cap keeps intervalSeconds*1000 under setInterval's TIMEOUT_MAX)
  return Math.min(86400, Math.max(60, (isFinite(n) && Math.round(n)) || 900));
}

export function parseSchedule(raw: unknown): Schedule {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const intervalSeconds = clampInterval(typeof o.intervalSeconds === "number" ? o.intervalSeconds : 900);
  return { enabled: o.enabled === true, intervalSeconds };
}

const schedulePath = (dir: string): string => join(dir, "scheduler.json");

export async function readSchedule(dir: string): Promise<Schedule> {
  try {
    return parseSchedule(JSON.parse(await readFile(schedulePath(dir), "utf8")));
  } catch {
    return DEFAULT_SCHEDULE;   // missing/corrupt -> off
  }
}

export async function writeSchedule(dir: string, s: Schedule): Promise<Schedule> {
  const clamped: Schedule = { enabled: s.enabled === true, intervalSeconds: clampInterval(s.intervalSeconds) };
  await mkdir(dir, { recursive: true });
  await writeFile(schedulePath(dir), JSON.stringify(clamped), "utf8");
  return clamped;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS — the 4 new tests + all existing (was 39, now 43).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/scheduler.ts desktop/src/lib/scheduler.test.ts
git commit -m "feat(dashboard): scheduler config lib (Schedule, clampInterval, parseSchedule, read/write)"
```

---

### Task 3: Main — scheduler manager + IPC + preload + startup arm (build-verified)

**Files:**
- Create: `desktop/src/main/scheduler.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts`

**Interfaces:**
- Consumes: `runBot` (Task 1); `Schedule`, `readSchedule`, `writeSchedule` (Task 2).
- Produces: IPC `run-bot` / `get-schedule` / `set-schedule`; `window.api.runBot()` / `getSchedule()` / `setSchedule(s)`; `applySchedule(s)` arming the timer.

- [ ] **Step 1: Create the scheduler manager**

Create `desktop/src/main/scheduler.ts`:

```ts
import { runBot } from "./engine";
import { Schedule } from "../lib/scheduler";

let handle: NodeJS.Timeout | null = null;
let inFlight = false;

export function applySchedule(s: Schedule): void {
  if (handle) { clearInterval(handle); handle = null; }
  if (!s.enabled) return;
  handle = setInterval(() => {
    if (inFlight) return;                          // skip pile-up; bot.lock is the real guard
    inFlight = true;
    runBot().finally(() => { inFlight = false; });
  }, s.intervalSeconds * 1000);
}
```

- [ ] **Step 2: Wire IPC + startup arm in `index.ts`**

In `desktop/src/main/index.ts`, change the engine import (currently `import { runBacktest } from "./engine";`) to:

```ts
import { runBacktest, runBot } from "./engine";
```

Add two more imports near it:

```ts
import { applySchedule } from "./scheduler";
import { readSchedule, writeSchedule } from "../lib/scheduler";
```

Inside `app.whenReady().then(() => { ... })`, immediately after the existing line:

```ts
    ipcMain.handle("run-backtest", (_e, opts) => runBacktest(opts));
```

add:

```ts
    ipcMain.handle("run-bot", () => runBot());
    ipcMain.handle("get-schedule", () => readSchedule(dataDir()));
    ipcMain.handle("set-schedule", async (_e, s) => {
      const saved = await writeSchedule(dataDir(), s);
      applySchedule(saved);
      return saved;
    });
    readSchedule(dataDir()).then(applySchedule);   // arm the schedule on startup
```

- [ ] **Step 3: Expose in preload**

In `desktop/src/preload/index.ts`, the `api` object currently has `getSnapshot`, `setMode`, `runBacktest`. Add three entries so it reads:

```ts
const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
  runBacktest: (opts: { since: string; until?: string }) => ipcRenderer.invoke("run-backtest", opts),
  runBot: () => ipcRenderer.invoke("run-bot"),
  getSchedule: () => ipcRenderer.invoke("get-schedule"),
  setSchedule: (s: { enabled: boolean; intervalSeconds: number }) => ipcRenderer.invoke("set-schedule", s),
};
```

- [ ] **Step 4: Verify the build**

Run: `cd desktop && npm run build`
Expected: exit 0 — `scheduler.ts`, the updated `index.ts`, and `preload/index.ts` compile.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/scheduler.ts desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(dashboard): main-process scheduler (setInterval runBot) + run-bot/get-schedule/set-schedule IPC + startup arm"
```

---

### Task 4: Renderer — Settings view + nav + wiring + styles + gitignore (Playwright-verified)

**Files:**
- Create: `desktop/src/renderer/src/components/Settings.tsx`
- Modify: `desktop/src/renderer/src/components/Sidebar.tsx` (add `settings` to `View` + `NAV`)
- Modify: `desktop/src/renderer/src/App.tsx` (import + render `<Settings />`)
- Modify: `desktop/src/renderer/src/index.css` (settings styles)
- Modify: `.gitignore` (ignore `data/scheduler.json`)

**Interfaces:**
- Consumes: `window.api.runBot()`, `window.api.getSchedule()`, `window.api.setSchedule(s)` (Task 3).

- [ ] **Step 1: Create the Settings component**

Create `desktop/src/renderer/src/components/Settings.tsx`:

```tsx
import { useEffect, useState } from "react";

type Schedule = { enabled: boolean; intervalSeconds: number };
type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: {
    runBot: () => Promise<{ ok: boolean; code: number | null; stderrTail: string }>;
    getSchedule: () => Promise<Schedule>;
    setSchedule: (s: Schedule) => Promise<Schedule>;
  };
}).api;

export default function Settings(): React.JSX.Element {
  const [enabled, setEnabled] = useState(false);
  const [intervalSeconds, setIntervalSeconds] = useState(900);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);

  useEffect(() => {
    api.getSchedule().then((s) => { setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s); });
  }, []);

  const save = async (): Promise<void> => {
    const s = await api.setSchedule({ enabled, intervalSeconds });
    setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s);
  };

  const runNow = async (): Promise<void> => {
    if (running) return;
    setRunning(true);
    setResult(null);
    try {
      const r = await api.runBot();
      setResult({ ok: r.ok, stderrTail: r.stderrTail });
    } catch (err) {
      setResult({ ok: false, stderrTail: String(err) });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="settings-form">
      <label className="settings-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Run the bot on a schedule (while this app is open)
      </label>
      <label className="settings-row">
        Interval (seconds)
        <input type="number" min={60} value={intervalSeconds}
               onChange={(e) => setIntervalSeconds(Number(e.target.value))} />
      </label>
      <div className="settings-actions">
        <button className="bt-run" onClick={save}>Save schedule</button>
        <button className="bt-run" disabled={running} onClick={runNow}>{running ? "Running…" : "Run now"}</button>
      </div>
      {saved && (
        <div className="settings-summary">
          {saved.enabled ? `Scheduler on — every ${saved.intervalSeconds}s` : "Scheduler off"} · keep the interval near
          {" "}config.interval_seconds for accurate freshness.
        </div>
      )}
      {result && result.ok && <div className="bt-result">Bot cycle complete — dashboard updating…</div>}
      {result && !result.ok && (
        <div className="bt-result bt-error">Bot run failed<pre>{result.stderrTail || "(no output)"}</pre></div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add the nav item**

In `desktop/src/renderer/src/components/Sidebar.tsx`, change the `View` type from:

```ts
export type View = "overview" | "positions" | "activity" | "sentiment" | "backtest";
```

to:

```ts
export type View = "overview" | "positions" | "activity" | "sentiment" | "backtest" | "settings";
```

and add a nav entry at the end of the `NAV` array (after the `backtest` entry):

```ts
  { id: "settings", label: "Settings" },
```

- [ ] **Step 3: Render the Settings view in App**

In `desktop/src/renderer/src/App.tsx`, add the import after the existing `BacktestForm` import:

```ts
import Settings from "./components/Settings";
```

Then add this block immediately after the `view === "backtest"` block (inside the same `<main className="main">`):

```tsx
        {view === "settings" && (
          <section className="card"><h2>Settings</h2><Settings /></section>
        )}
```

- [ ] **Step 4: Add styles**

Append to `desktop/src/renderer/src/index.css`:

```css
.settings-form { display: flex; flex-direction: column; gap: 14px; max-width: 480px; }
.settings-row { display: flex; align-items: center; gap: 10px; font-size: 14px; color: var(--text); }
.settings-row input[type="number"] { width: 120px; background: var(--glass); border: 1px solid var(--glass-border);
  border-radius: 8px; color: var(--text); font: inherit; padding: 7px 10px; }
.settings-actions { display: flex; gap: 10px; }
.settings-summary { font-size: 13px; color: var(--muted); }
```

- [ ] **Step 5: gitignore the runtime file**

In `.gitignore`, after the existing `data/control.json` line, add:

```gitignore
data/scheduler.json
```

- [ ] **Step 6: Build + full vitest**

Run: `cd desktop && npm test && npm run build`
Expected: vitest green (43, unchanged — no lib change here); build exit 0.

- [ ] **Step 7: Playwright verify (controller does this; 1280/768/375)**

Serve `desktop/out/renderer`, stub `window.api` (including `getSchedule` resolving `{ enabled:false, intervalSeconds:900 }`, `setSchedule` echoing its arg, `runBot`) via `addInitScript`. Navigate to the Settings nav item and confirm:
- the form renders (enabled checkbox + interval input + Save + Run now);
- `getSchedule` populates it (interval 900);
- toggling enabled + Save calls `setSchedule` and the summary reflects it ("Scheduler on — every 900s");
- Run now with a stubbed `{ ok:true }` shows "Running…" then "Bot cycle complete…"; with `{ ok:false, stderrTail:"boom" }` renders the error `<pre>`.

(Controller verification, not the implementer's — the implementer completes Steps 1-6 and commits.)

- [ ] **Step 8: Commit**

```bash
git add desktop/src/renderer/src/components/Settings.tsx desktop/src/renderer/src/components/Sidebar.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css .gitignore
git commit -m "feat(dashboard): Settings view — scheduler toggle/interval + Run now, wired to IPC"
```

---

## Self-Review

**Spec coverage:**
- `spawnEngine` extraction + `runBot` (shared pinnedEnv) → Task 1 ✓
- `Schedule`/`clampInterval`/`parseSchedule`/`read`/`writeSchedule` → Task 2 ✓
- main scheduler manager (`applySchedule`, skip in-flight) + IPC + preload + startup arm → Task 3 ✓
- Settings view (enabled/interval/Save/Run-now states), nav item, App wiring, CSS, gitignore → Task 4 ✓
- Default off, floor 60, default 900 → Task 2 (`DEFAULT_SCHEDULE`, `clampInterval`) ✓
- Safety (every spawn via `spawnEngine`→`pinnedEnv`) → Task 1 ✓

**Placeholder scan:** none — every code step shows complete code or exact insertion text.

**Type consistency:**
- `Schedule = { enabled: boolean; intervalSeconds: number }` defined Task 2, consumed verbatim in Task 3 (IPC/`writeSchedule`/`applySchedule`) and Task 4 (Settings/preload) ✓
- `RunResult` (existing) returned by `runBot` (Task 1), read by Settings' `runNow` (`ok`/`stderrTail`) ✓
- IPC channel names `run-bot`/`get-schedule`/`set-schedule` match across main handlers + preload ✓
- `applySchedule(s: Schedule)` (Task 3) called with the clamped `Schedule` from `writeSchedule`/`readSchedule` ✓
