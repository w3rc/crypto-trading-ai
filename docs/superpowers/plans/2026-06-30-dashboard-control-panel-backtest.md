# Dashboard Control Panel — Phase 1 (Run Backtest) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the dashboard run a backtest from the UI — a Since/Until form + Run button spawns `python -m engine.backtest`, and the existing chart fills from the engine's CSV output.

**Architecture:** The Electron main process spawns the Python engine via `child_process.spawn`; the renderer asks over IPC; the engine writes `data/backtest_equity.csv`; the dashboard's existing 5 s poll renders it. A pure, unit-tested helper builds the argv; the spawn itself is build- + manually-verified. This is the reusable foundation for Phase 2 (run-now + scheduler).

**Tech Stack:** Electron + React + TypeScript, electron-vite, vitest (node env, `src/lib/**`). Python 3.14 engine (unchanged). No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-06-30-dashboard-control-panel-backtest-design.md`

## Global Constraints

- **No new dependencies.** Use native `<input type="date">` and Node built-ins (`child_process`, `fs`, `path`).
- **Safety (highest priority):** the spawn env MUST strip `LIVE_TRADING_ARMED` (`delete env.LIVE_TRADING_ARMED`) so a dashboard-launched process can never arm live. NO change to the live-trading safety model, the mode toggle, or `create_order`. Backtest places no orders regardless.
- **vitest covers `src/lib/**` only.** The pure helpers (`buildBacktestArgs`, `isIsoDate`) get unit tests. The main-process `engine.ts` (spawn) and the renderer `BacktestForm` are verified by `npm run build` (exit 0) and Playwright — no unit test for the spawn.
- **Dev-local:** `repoRoot`/venv are derived from `dataDir()`'s parent. Packaged-app python bundling is out of scope.
- **Commit trailers** (every commit; verify with `git log --format="%B" -1 HEAD`, amend if missing):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Desktop commands from `desktop/`: `npm test`, `npm run build`. Do NOT push. (No Python change — the engine suite is unaffected.)

---

### Task 1: Lib — backtest arg builder + date validator (pure, unit-tested)

**Files:**
- Create: `desktop/src/lib/backtest.ts`
- Test: `desktop/src/lib/backtest.test.ts`

**Interfaces:**
- Produces:
  - `type BacktestOpts = { since: string; until?: string }`
  - `buildBacktestArgs(opts: BacktestOpts): string[]` — the argv after the python executable.
  - `isIsoDate(s: string): boolean` — true iff `s` matches `YYYY-MM-DD`.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/lib/backtest.test.ts`:

```ts
import { test, expect } from "vitest";
import { buildBacktestArgs, isIsoDate } from "./backtest";

test("buildBacktestArgs with since only", () => {
  expect(buildBacktestArgs({ since: "2026-01-01" })).toEqual([
    "-m", "engine.backtest", "--since", "2026-01-01", "--out", "data/backtest_equity.csv",
  ]);
});

test("buildBacktestArgs with since and until", () => {
  expect(buildBacktestArgs({ since: "2026-01-01", until: "2026-03-01" })).toEqual([
    "-m", "engine.backtest",
    "--since", "2026-01-01",
    "--until", "2026-03-01",
    "--out", "data/backtest_equity.csv",
  ]);
});

test("isIsoDate validates YYYY-MM-DD", () => {
  expect(isIsoDate("2026-01-01")).toBe(true);
  expect(isIsoDate("2026-1-1")).toBe(false);
  expect(isIsoDate("")).toBe(false);
  expect(isIsoDate("not a date")).toBe(false);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/backtest.test.ts`
Expected: FAIL — `./backtest` does not exist (import/collection error).

- [ ] **Step 3: Implement**

Create `desktop/src/lib/backtest.ts`:

```ts
export type BacktestOpts = { since: string; until?: string };

export function isIsoDate(s: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}

export function buildBacktestArgs(opts: BacktestOpts): string[] {
  return [
    "-m", "engine.backtest",
    "--since", opts.since,
    ...(opts.until ? ["--until", opts.until] : []),
    "--out", "data/backtest_equity.csv",
  ];
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS — the 3 new tests + all existing (was 34, now 37).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/backtest.ts desktop/src/lib/backtest.test.ts
git commit -m "feat(dashboard): backtest arg builder + ISO date validator (pure, unit-tested)"
```

---

### Task 2: Main — `runBacktest` spawn + IPC + preload (build-verified)

**Files:**
- Create: `desktop/src/main/engine.ts`
- Modify: `desktop/src/main/index.ts` (add the `run-backtest` IPC handler)
- Modify: `desktop/src/preload/index.ts` (expose `runBacktest`)

**Interfaces:**
- Consumes: `buildBacktestArgs`, `isIsoDate`, `BacktestOpts` (Task 1); `dataDir` from `../lib/snapshot`.
- Produces:
  - `runBacktest(opts: BacktestOpts): Promise<RunResult>` where `RunResult = { ok: boolean; code: number | null; stderrTail: string }`.
  - IPC channel `"run-backtest"` and `window.api.runBacktest(opts) => Promise<RunResult>`.

- [ ] **Step 1: Create the spawn module**

Create `desktop/src/main/engine.ts`:

```ts
import { spawn } from "child_process";
import { existsSync } from "fs";
import { join, resolve } from "path";
import { dataDir } from "../lib/snapshot";
import { buildBacktestArgs, isIsoDate, BacktestOpts } from "../lib/backtest";

export type RunResult = { ok: boolean; code: number | null; stderrTail: string };

function pythonPath(repoRoot: string): string {
  const venv = join(repoRoot, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

// ponytail: dev-local repoRoot/venv resolution; packaged-app python bundling (deferred C1) is out of scope.
export function runBacktest(opts: BacktestOpts): Promise<RunResult> {
  if (!isIsoDate(opts.since)) {
    return Promise.resolve({ ok: false, code: null, stderrTail: `invalid since date: ${opts.since} (expected YYYY-MM-DD)` });
  }
  const repoRoot = resolve(dataDir(), "..");
  const env = { ...process.env };
  delete env.LIVE_TRADING_ARMED;          // a dashboard-launched process can never arm live
  return new Promise((resolveP) => {
    const child = spawn(pythonPath(repoRoot), buildBacktestArgs(opts), { cwd: repoRoot, env });
    let stderr = "";
    child.stderr.on("data", (d) => { stderr = (stderr + d.toString()).slice(-2048); });
    child.on("error", (e) => resolveP({ ok: false, code: null, stderrTail: e.message }));
    child.on("close", (code) => resolveP({ ok: code === 0, code, stderrTail: stderr.trim() }));
  });
}
```

- [ ] **Step 2: Register the IPC handler**

In `desktop/src/main/index.ts`, add the import near the other local imports (after the `writeControl` import):

```ts
import { runBacktest } from "./engine";
```

Then, inside `app.whenReady().then(() => { ... })`, immediately after the existing line:

```ts
    ipcMain.handle("set-mode", (_e, mode: string) => writeControl(dataDir(), mode));
```

add:

```ts
    ipcMain.handle("run-backtest", (_e, opts) => runBacktest(opts));
```

- [ ] **Step 3: Expose it in preload**

In `desktop/src/preload/index.ts`, the `api` object currently is:

```ts
const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
};
```

Replace it with:

```ts
const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
  runBacktest: (opts: { since: string; until?: string }) => ipcRenderer.invoke("run-backtest", opts),
};
```

- [ ] **Step 4: Verify the build**

Run: `cd desktop && npm run build`
Expected: exit 0 — `engine.ts`, the updated `index.ts`, and `preload/index.ts` all compile (main + preload + renderer bundles build).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/engine.ts desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(dashboard): main-process runBacktest spawn + run-backtest IPC + preload (strips LIVE_TRADING_ARMED)"
```

---

### Task 3: Renderer — Backtest form + wiring + styles (Playwright-verified)

**Files:**
- Create: `desktop/src/renderer/src/components/BacktestForm.tsx`
- Modify: `desktop/src/renderer/src/App.tsx` (import + render `<BacktestForm />` in the backtest view)
- Modify: `desktop/src/renderer/src/index.css` (form styles)

**Interfaces:**
- Consumes: `window.api.runBacktest(opts) => Promise<{ ok: boolean; code: number | null; stderrTail: string }>` (Task 2).

- [ ] **Step 1: Create the form component**

Create `desktop/src/renderer/src/components/BacktestForm.tsx`:

```tsx
import { useState } from "react";

type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: { runBacktest: (o: { since: string; until?: string }) => Promise<{ ok: boolean; code: number | null; stderrTail: string }> };
}).api;

export default function BacktestForm(): React.JSX.Element {
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);

  const run = async (): Promise<void> => {
    if (!since || running) return;
    setRunning(true);
    setResult(null);
    const r = await api.runBacktest({ since, until: until || undefined });
    setRunning(false);
    setResult({ ok: r.ok, stderrTail: r.stderrTail });
  };

  return (
    <div className="bt-form">
      <label>Since<input type="date" value={since} onChange={(e) => setSince(e.target.value)} /></label>
      <label>Until<input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
      <button className="bt-run" disabled={!since || running} onClick={run}>
        {running ? "Running…" : "Run backtest"}
      </button>
      {result && result.ok && <div className="bt-result">Backtest complete — chart updating…</div>}
      {result && !result.ok && (
        <div className="bt-result bt-error">Backtest failed<pre>{result.stderrTail || "(no output)"}</pre></div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire it into the Backtest view**

In `desktop/src/renderer/src/App.tsx`, add the import after the existing `BacktestChart` import:

```ts
import BacktestForm from "./components/BacktestForm";
```

Then change the backtest view block from:

```tsx
        {view === "backtest" && (
          <section className="card"><h2>Backtest</h2><BacktestChart points={snap.backtest} /></section>
        )}
```

to:

```tsx
        {view === "backtest" && (
          <section className="card"><h2>Backtest</h2><BacktestForm /><BacktestChart points={snap.backtest} /></section>
        )}
```

- [ ] **Step 3: Add the form styles**

In `desktop/src/renderer/src/index.css`, append:

```css
.bt-form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 14px; margin-bottom: 16px; }
.bt-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.bt-form input { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px;
  color: var(--text); font: inherit; padding: 7px 10px; color-scheme: dark; }
.bt-run { background: var(--accent); color: #0a0e1a; border: none; border-radius: 8px; font: inherit;
  font-weight: 600; padding: 8px 16px; cursor: pointer; }
.bt-run:disabled { opacity: 0.5; cursor: not-allowed; }
.bt-result { width: 100%; font-size: 13px; color: var(--muted); margin-top: 4px; }
.bt-error { color: var(--down); }
.bt-result pre { white-space: pre-wrap; font-size: 12px; margin: 6px 0 0; color: var(--muted); }
```

- [ ] **Step 4: Build + full vitest**

Run: `cd desktop && npm test && npm run build`
Expected: vitest green (37, unchanged — no lib change here); build exit 0.

- [ ] **Step 5: Playwright verify (controller does this; 1280/768/375)**

Serve `desktop/out/renderer` and stub `window.api` (including `runBacktest`) via `addInitScript` before the bundle loads. Confirm on the Backtest tab:
- the form renders (Since + Until date inputs + Run button);
- Run is disabled until Since is set;
- clicking Run with a stubbed `runBacktest` that resolves `{ ok:true }` shows "Running…" then "Backtest complete — chart updating…";
- a stub resolving `{ ok:false, stderrTail:"boom" }` renders the error `<pre>` with "boom".

(This step is the controller's verification, not the implementer's — the implementer completes Steps 1-4 and commits.)

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/src/components/BacktestForm.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): Backtest run form (Since/Until + Run) wired to runBacktest"
```

---

## Self-Review

**Spec coverage:**
- Spawn foundation (`buildBacktestArgs`/`isIsoDate` in lib; `runBacktest` in main; IPC; preload) → Tasks 1 + 2 ✓
- `LIVE_TRADING_ARMED` stripped from spawn env → Task 2 Step 1 ✓
- Backtest form (Since required / Until optional / Run; running + result states; native date inputs) → Task 3 ✓
- Wired above the existing `BacktestChart`; 5 s poll fills the chart → Task 3 Step 2 ✓
- Dev-local repoRoot/venv resolution, packaged-app out of scope → Task 2 ponytail comment ✓
- Testing: vitest for pure helpers; build + Playwright for spawn/form → Tasks 1/2/3 ✓

**Placeholder scan:** none — every code step shows complete code or exact insertion text.

**Type consistency:**
- `BacktestOpts = { since: string; until?: string }` defined in Task 1, consumed verbatim in Task 2 (`runBacktest`) and Task 3 (`window.api.runBacktest`/preload) ✓
- `RunResult = { ok: boolean; code: number | null; stderrTail: string }` produced by Task 2, consumed by Task 3's `api` type (form only reads `ok` + `stderrTail`) ✓
- IPC channel name `"run-backtest"` matches across main handler + preload ✓
