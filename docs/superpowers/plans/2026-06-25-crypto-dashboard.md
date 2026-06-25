# Crypto Bot Dashboard — Electron Desktop App (Plan 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only **Electron desktop app** (dark/gradient/glass aesthetic) showing the paper-trading bot's equity curve, open positions, and per-cycle decision log — reading the files the Python engine writes, decoupled from it.

**Architecture:** Two parts. **(A)** A tiny engine addition: each cycle appends every symbol's decision (action, reason, price, executed) to `data/decisions.jsonl`, so the LLM's reasoning (incl. HOLDs) is persisted, not just printed. **(B)** An Electron app in `desktop/` (electron-vite + React): the **main** process reads `data/{state.json,trades.csv,decisions.jsonl}` from disk and answers an IPC `snapshot` request; a `contextBridge` **preload** exposes `window.api.getSnapshot()`; the **renderer** (React + Recharts) polls it every few seconds and renders three glass panels. The app NEVER writes and NEVER imports engine code — it only reads the files.

**Tech Stack:** Part A: Python 3.12 (existing engine). Part B: Electron · electron-vite · Vite · React · TypeScript · Recharts (equity chart) · hand-written CSS (dark/glass) · Vitest (unit tests for the pure parse/read layer).

## Global Constraints

- **Read-only.** The app only reads the `data/` files; it never writes them and never imports any `engine/` module. The two runtimes share nothing but the files on disk.
- **Tolerate missing/partial files.** The engine may not have run yet — a missing `state.json`/`trades.csv`/`decisions.jsonl` renders an empty-but-valid window, never throws.
- **Data location is configurable.** The main process reads from `process.env.DATA_DIR` if set, else `<desktop>/../data` (the repo's `data/` dir). Default works in `electron-vite dev` (cwd = `desktop/`). Packaged builds set `DATA_DIR` (noted; packaging itself is v2).
- **No fs in the renderer.** Only the Electron **main** process touches the filesystem (`snapshot.ts`). The renderer imports **types only** from `parse.ts` and gets data exclusively via `window.api.getSnapshot()` (IPC). `contextIsolation` stays on; the preload exposes a single minimal function.
- **Decision record schema (the A↔B contract), one JSON object per line in `data/decisions.jsonl`:** `{"ts": str, "symbol": str, "action": "buy"|"sell"|"hold", "reason": str, "price": float, "executed": bool}`. `executed` is true only when a fill happened. This MUST equal the TypeScript `Decision` type field-for-field.
- **Aesthetic:** dark background with a subtle gradient; translucent "glass" cards (blur + subtle border); legible typography. A *data* dashboard — clarity over animation.
- **Engine code already on `main` keeps passing** — the Part A change is additive (40 existing tests stay green).
- Branch: `feat/dashboard` (off `main`). Lands via a PR against `main`.

---

## File Structure

```
# Part A — engine addition (Python)
engine/state.py        # + append_decision(record, data_dir) -> data/decisions.jsonl
engine/bot.py          # + log every symbol's decision each cycle
.gitignore             # + data/decisions.jsonl

# Part B — Electron app (electron-vite + React), reads data/ only
desktop/
  package.json, electron.vite.config.ts, tsconfig*.json   # from scaffold
  vitest.config.ts                       # scopes vitest to src/lib (node env)
  src/
    lib/parse.ts        # pure: parseTradesCsv, parseDecisions + shared types (NO fs)
    lib/parse.test.ts   # vitest (pure)
    lib/snapshot.ts     # readSnapshot(dataDir) + dataDir() — Node fs; used by MAIN only
    lib/snapshot.test.ts# vitest against a temp dir
    main/index.ts       # BrowserWindow + ipcMain.handle("snapshot", ...) — OVERWRITTEN
    preload/index.ts    # contextBridge: window.api.getSnapshot() — OVERWRITTEN
    renderer/src/
      main.tsx          # imports index.css, renders <App/> — OVERWRITTEN
      index.css         # dark/gradient/glass theme
      App.tsx           # polls window.api.getSnapshot() every 5s, renders panels — OVERWRITTEN
      components/EquityChart.tsx     # Recharts area chart
      components/PositionsTable.tsx  # cash + open positions
      components/DecisionLog.tsx     # recent decisions
  README.md
```

---

### Task 1: Engine — persist decisions to `data/decisions.jsonl`

**Files:**
- Modify: `engine/state.py` (append `append_decision`), `engine/bot.py` (log each decision), `.gitignore`
- Test: `tests/test_state.py`, `tests/test_bot.py`

**Interfaces:**
- Consumes: existing `engine/state.py`, `engine/bot.py`.
- Produces: `append_decision(record: dict, data_dir: str) -> None` (appends `json.dumps(record)` + newline to `data/decisions.jsonl`). `run_once` writes one decision record per *priced* symbol per cycle (skipped symbols write nothing).

- [ ] **Step 1: Write the failing test** — append to `tests/test_state.py`

```python
import json as _json
from engine.state import append_decision

def test_append_decision_writes_jsonl(tmp_path):
    append_decision({"ts": "t1", "symbol": "BTC/USDT", "action": "hold",
                     "reason": "weak signal", "price": 60000.0, "executed": False}, str(tmp_path))
    append_decision({"ts": "t2", "symbol": "ETH/USDT", "action": "buy",
                     "reason": "oversold", "price": 1600.0, "executed": True}, str(tmp_path))
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec = _json.loads(lines[1])
    assert rec["action"] == "buy" and rec["executed"] is True and rec["symbol"] == "ETH/USDT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_state.py::test_append_decision_writes_jsonl -v`
Expected: FAIL with `ImportError: cannot import name 'append_decision'`

- [ ] **Step 3: Add `append_decision` to `engine/state.py`** (near `append_trade`; the file already imports `json`, `os`)

```python
def append_decision(record: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "decisions.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_state.py::test_append_decision_writes_jsonl -v`
Expected: PASS

- [ ] **Step 5: Write the failing wiring tests** — append to `tests/test_bot.py`

```python
import json as _json

def test_decisions_are_logged_each_cycle(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), llm=FakeLLM(Decision(action="buy", size=1.0)))
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1                      # one priced symbol -> one decision record
    rec = _json.loads(lines[0])
    assert rec["symbol"] == "BTC/USDT"
    assert rec["action"] == "buy" and rec["executed"] is True
    assert "price" in rec and "reason" in rec and "ts" in rec

def test_hold_decision_is_logged_not_executed(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), llm=FakeLLM(Decision(action="hold", reason="flat")))
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip())
    assert rec["action"] == "hold" and rec["executed"] is False and rec["reason"] == "flat"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_bot.py::test_decisions_are_logged_each_cycle -v`
Expected: FAIL (no `decisions.jsonl` written yet)

- [ ] **Step 7: Wire decision logging into `engine/bot.py`**

In `run_once`, replace the block beginning at `if order is None:` (right after `reason` is set) with this — a decision is logged for every priced symbol BEFORE the HOLD/fill split:

```python
            action = order.side if order else "hold"
            state_mod.append_decision(
                {"ts": ts, "symbol": sym, "action": action, "reason": reason,
                 "price": price, "executed": order is not None},
                cfg.data_dir)

            if order is None:
                print(f"[{sym}] HOLD @ {price:.2f} — {reason}")
                continue

            new_pos, new_cash, fill = broker.apply_fill(
                order, pos, st.cash, cfg.fee_pct, cfg.slippage_pct,
                cfg.risk.stop_loss_pct, ts)
            st.positions[sym] = new_pos
            st.cash = new_cash
            state_mod.append_trade(fill, cfg.data_dir)
            print(f"[{sym}] {order.side.upper()} {order.qty:.6f} @ {fill.price:.2f} — {reason}")
```

(Everything above — fetch, price guard, stop/LLM, `order`/`reason` — stays unchanged.)

- [ ] **Step 8: Run the wiring tests + full suite**

Run: `.venv/bin/python -m pytest tests/test_bot.py -v` → PASS (incl. the 2 new)
Run: `.venv/bin/python -m pytest -q` → all pass (42 tests).

- [ ] **Step 9: Add `data/decisions.jsonl` to `.gitignore`** (under the other `data/` entries)

- [ ] **Step 10: Commit**

```bash
git add engine/state.py engine/bot.py tests/test_state.py tests/test_bot.py .gitignore
git commit -m "feat(engine): persist per-cycle decisions to data/decisions.jsonl"
```

---

### Task 2: Scaffold the Electron app (`desktop/`)

**Files:**
- Create: `desktop/` (via electron-vite scaffold) + `recharts` + `vitest` deps + `desktop/vitest.config.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: a runnable electron-vite + React + TS app at `desktop/`. `npm run build` succeeds. The scaffold writes its own `.gitignore` (covers `node_modules/`, `out/`, `dist/`).

- [ ] **Step 1: Scaffold** (from repo root)

```bash
npm create @quick-start/electron@latest desktop -- --template react-ts
```
If prompted for optional ESLint/Prettier, either choice is fine (decline to keep it lean). This creates `desktop/` with `src/main/index.ts`, `src/preload/index.ts`, `src/renderer/`, `electron.vite.config.ts`, and `package.json` (scripts: `dev`, `build`, `start`).

- [ ] **Step 2: Install deps**

```bash
cd desktop
npm install
npm install recharts
npm install -D vitest
```

- [ ] **Step 3: Add a vitest config + test script**

Create `desktop/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["src/lib/**/*.test.ts"], environment: "node" },
});
```
In `desktop/package.json` add to `"scripts"`: `"test": "vitest run"`.

- [ ] **Step 4: Verify the scaffold runs/builds**

Run: `cd desktop && npm run build`
Expected: electron-vite builds main + preload + renderer with no errors (default demo window).

- [ ] **Step 5: Commit**

```bash
git add desktop/
git commit -m "chore(desktop): scaffold electron-vite + React + recharts + vitest"
```

---

### Task 3: Pure parsers + types (`src/lib/parse.ts`)

**Files:**
- Create: `desktop/src/lib/parse.ts`, `desktop/src/lib/parse.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: types `EquityPoint`, `Position`, `State`, `Trade`, `Decision`, `Snapshot`; pure functions `parseTradesCsv(text): Trade[]` and `parseDecisions(text): Decision[]`. Both tolerate empty/whitespace input → `[]`. NO `fs` import (so the renderer can import the types safely).

- [ ] **Step 1: Write the failing test** — `desktop/src/lib/parse.test.ts`

```ts
import { test, expect } from "vitest";
import { parseTradesCsv, parseDecisions } from "./parse";

test("parseTradesCsv parses header + rows, coerces numbers", () => {
  const csv = "ts,symbol,side,qty,price,fee\nt1,BTC/USDT,buy,0.5,60000,0.3\nt2,BTC/USDT,sell,0.5,61000,0.305\n";
  const trades = parseTradesCsv(csv);
  expect(trades).toHaveLength(2);
  expect(trades[0]).toEqual({ ts: "t1", symbol: "BTC/USDT", side: "buy", qty: 0.5, price: 60000, fee: 0.3 });
  expect(trades[1].side).toBe("sell");
});

test("parseTradesCsv tolerates empty / header-only input", () => {
  expect(parseTradesCsv("")).toEqual([]);
  expect(parseTradesCsv("ts,symbol,side,qty,price,fee\n")).toEqual([]);
});

test("parseDecisions parses jsonl, skips blank lines", () => {
  const jsonl = '{"ts":"t1","symbol":"BTC/USDT","action":"hold","reason":"weak","price":60000,"executed":false}\n\n'
              + '{"ts":"t2","symbol":"ETH/USDT","action":"buy","reason":"dip","price":1600,"executed":true}\n';
  const ds = parseDecisions(jsonl);
  expect(ds).toHaveLength(2);
  expect(ds[1]).toEqual({ ts: "t2", symbol: "ETH/USDT", action: "buy", reason: "dip", price: 1600, executed: true });
});

test("parseDecisions tolerates empty input", () => {
  expect(parseDecisions("")).toEqual([]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/lib/parse.test.ts`
Expected: FAIL (cannot find module `./parse`)

- [ ] **Step 3: Write `desktop/src/lib/parse.ts`**

```ts
export type EquityPoint = { ts: string; equity: number };
export type Position = { qty: number; avg_price: number; stop_price: number };
export type State = { cash: number; positions: Record<string, Position>; equity_history: EquityPoint[] };
export type Trade = { ts: string; symbol: string; side: string; qty: number; price: number; fee: number };
export type Decision = { ts: string; symbol: string; action: string; reason: string; price: number; executed: boolean };
export type Snapshot = { state: State | null; trades: Trade[]; decisions: Decision[] };

export function parseTradesCsv(text: string): Trade[] {
  const lines = text.trim().split("\n").filter((l) => l.trim() !== "");
  if (lines.length <= 1) return []; // empty or header-only
  return lines.slice(1).map((line) => {
    const [ts, symbol, side, qty, price, fee] = line.split(",");
    return { ts, symbol, side, qty: Number(qty), price: Number(price), fee: Number(fee) };
  });
}

export function parseDecisions(text: string): Decision[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l !== "")
    .map((l) => JSON.parse(l) as Decision);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/lib/parse.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/parse.test.ts
git commit -m "feat(desktop): pure CSV/JSONL parsers + shared types"
```

---

### Task 4: Snapshot reader (Node) + main IPC + preload bridge

**Files:**
- Create: `desktop/src/lib/snapshot.ts`, `desktop/src/lib/snapshot.test.ts`
- Overwrite: `desktop/src/main/index.ts`, `desktop/src/preload/index.ts`

**Interfaces:**
- Consumes: `parse.ts`.
- Produces: `readSnapshot(dataDir): Promise<Snapshot>` (missing file → empty value, never throws) and `dataDir(): string` (`process.env.DATA_DIR || resolve(process.cwd(), "..", "data")`). Main registers `ipcMain.handle("snapshot", () => readSnapshot(dataDir()))`. Preload exposes `window.api.getSnapshot(): Promise<Snapshot>`.

- [ ] **Step 1: Write the failing test** — `desktop/src/lib/snapshot.test.ts`

```ts
import { test, expect } from "vitest";
import { mkdtempSync, writeFileSync, rmSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { readSnapshot } from "./snapshot";

test("readSnapshot reads all three files", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-"));
  writeFileSync(join(dir, "state.json"), JSON.stringify({
    cash: 8000, positions: { "BTC/USDT": { qty: 0.1, avg_price: 60000, stop_price: 57000 } },
    equity_history: [{ ts: "t1", equity: 10000 }, { ts: "t2", equity: 10100 }],
  }));
  writeFileSync(join(dir, "trades.csv"), "ts,symbol,side,qty,price,fee\nt1,BTC/USDT,buy,0.1,60000,0.06\n");
  writeFileSync(join(dir, "decisions.jsonl"),
    '{"ts":"t1","symbol":"BTC/USDT","action":"buy","reason":"dip","price":60000,"executed":true}\n');
  const snap = await readSnapshot(dir);
  expect(snap.state?.cash).toBe(8000);
  expect(snap.trades).toHaveLength(1);
  expect(snap.decisions[0].action).toBe("buy");
  rmSync(dir, { recursive: true, force: true });
});

test("readSnapshot tolerates a totally empty data dir", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-empty-"));
  const snap = await readSnapshot(dir);
  expect(snap.state).toBeNull();
  expect(snap.trades).toEqual([]);
  expect(snap.decisions).toEqual([]);
  rmSync(dir, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/lib/snapshot.test.ts`
Expected: FAIL (cannot find module `./snapshot`)

- [ ] **Step 3: Write `desktop/src/lib/snapshot.ts`**

```ts
import { readFile } from "fs/promises";
import { join, resolve } from "path";
import { parseTradesCsv, parseDecisions, Snapshot, State } from "./parse";

export function dataDir(): string {
  return process.env.DATA_DIR || resolve(process.cwd(), "..", "data");
}

async function readOr<T>(path: string, fallback: T, transform: (s: string) => T): Promise<T> {
  try {
    return transform(await readFile(path, "utf8"));
  } catch {
    return fallback; // missing/unreadable file -> empty value, never throw
  }
}

export async function readSnapshot(dir: string): Promise<Snapshot> {
  const state = await readOr<State | null>(join(dir, "state.json"), null, (s) => JSON.parse(s) as State);
  const trades = await readOr(join(dir, "trades.csv"), [], parseTradesCsv);
  const decisions = await readOr(join(dir, "decisions.jsonl"), [], parseDecisions);
  return { state, trades, decisions };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/lib/snapshot.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Overwrite `desktop/src/main/index.ts`** (window + IPC handler; no icon-asset dependency)

```ts
import { app, BrowserWindow, ipcMain } from "electron";
import { join } from "path";
import { is } from "@electron-toolkit/utils";
import { readSnapshot, dataDir } from "../lib/snapshot";

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1200,
    height: 820,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: "#0a0e1a",
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
    },
  });

  win.on("ready-to-show", () => win.show());

  if (is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    win.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    win.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(() => {
  ipcMain.handle("snapshot", () => readSnapshot(dataDir()));
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
```

- [ ] **Step 6: Overwrite `desktop/src/preload/index.ts`** (single minimal bridge)

```ts
import { contextBridge, ipcRenderer } from "electron";

const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
};

if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld("api", api);
  } catch (error) {
    console.error(error);
  }
} else {
  // @ts-ignore — fallback when contextIsolation is off
  window.api = api;
}
```

- [ ] **Step 7: Verify the lib suite + a full build**

Run: `cd desktop && npx vitest run` → PASS (parse + snapshot)
Run: `cd desktop && npm run build` → builds main (with the IPC handler + snapshot import), preload, and renderer with no errors.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/lib/snapshot.ts desktop/src/lib/snapshot.test.ts desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(desktop): snapshot reader + main IPC + preload bridge"
```

---

### Task 5: Renderer UI — panels, polling, dark/glass theme

**Files:**
- Overwrite: `desktop/src/renderer/src/main.tsx`, `desktop/src/renderer/src/App.tsx`
- Create: `desktop/src/renderer/src/index.css`, and `desktop/src/renderer/src/components/{EquityChart,PositionsTable,DecisionLog}.tsx`

**Interfaces:**
- Consumes: types from `../../lib/parse`; `window.api.getSnapshot()` at runtime.
- Produces: a polling React app (5s) rendering three glass panels. No unit tests (UI is verified by build here + Playwright in Task 6).

- [ ] **Step 1: Create `desktop/src/renderer/src/index.css`** (dark/gradient/glass theme)

```css
:root {
  --bg0: #0a0e1a; --bg1: #131a2e;
  --glass: rgba(255,255,255,0.05); --glass-border: rgba(255,255,255,0.10);
  --text: #e8edf7; --muted: #93a0bd; --up: #34d399; --down: #f87171; --accent: #7c8bff;
}
* { box-sizing: border-box; }
html, body, #root { margin: 0; padding: 0; min-height: 100vh; }
body {
  background: radial-gradient(1200px 600px at 80% -10%, #1d2748 0%, transparent 60%),
              linear-gradient(160deg, var(--bg0), var(--bg1));
  color: var(--text);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 28px 22px 56px; }
.title { font-size: 22px; font-weight: 700; }
.sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
.grid { display: grid; gap: 18px; margin-top: 20px; }
@media (min-width: 820px) { .grid { grid-template-columns: 1fr 1fr; } .span2 { grid-column: 1 / -1; } }
.card {
  background: var(--glass); border: 1px solid var(--glass-border); border-radius: 16px;
  padding: 18px 20px; backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  box-shadow: 0 8px 30px rgba(0,0,0,0.25);
}
.card h2 { margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
.kpis { display: flex; gap: 28px; flex-wrap: wrap; }
.kpi .label { color: var(--muted); font-size: 12px; }
.kpi .value { font-size: 26px; font-weight: 700; margin-top: 2px; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid rgba(255,255,255,0.06); }
th { color: var(--muted); font-weight: 600; font-size: 12px; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.badge.buy { background: rgba(52,211,153,0.15); color: var(--up); }
.badge.sell { background: rgba(248,113,113,0.15); color: var(--down); }
.badge.hold { background: rgba(147,160,189,0.15); color: var(--muted); }
.muted { color: var(--muted); } .right { text-align: right; }
.empty { color: var(--muted); padding: 18px 0; }
.chartbox { height: 280px; }
```

- [ ] **Step 2: Overwrite `desktop/src/renderer/src/main.tsx`**

```tsx
import "./index.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 3: Create `desktop/src/renderer/src/components/EquityChart.tsx`**

```tsx
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { EquityPoint } from "../../../lib/parse";

export default function EquityChart({ history }: { history: EquityPoint[] }) {
  if (!history.length) return <div className="empty">No equity history yet — run the bot.</div>;
  const data = history.map((p, i) => ({ i, equity: p.equity, ts: p.ts }));
  return (
    <div className="chartbox">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#7c8bff" stopOpacity={0.5} />
              <stop offset="100%" stopColor="#7c8bff" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="i" hide />
          <YAxis stroke="#93a0bd" width={64} domain={["auto", "auto"]} tickFormatter={(v) => `$${Math.round(v)}`} />
          <Tooltip
            contentStyle={{ background: "#131a2e", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, color: "#e8edf7" }}
            formatter={(v: number) => [`$${v.toFixed(2)}`, "equity"]}
            labelFormatter={(_, p) => (p && p[0] ? String(p[0].payload.ts) : "")}
          />
          <Area type="monotone" dataKey="equity" stroke="#7c8bff" strokeWidth={2} fill="url(#eq)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 4: Create `desktop/src/renderer/src/components/PositionsTable.tsx`**

```tsx
import type { State } from "../../../lib/parse";

export default function PositionsTable({ state }: { state: State | null }) {
  const positions = state ? Object.entries(state.positions).filter(([, p]) => p.qty > 0) : [];
  if (positions.length === 0) return <div className="empty">Flat — no open positions.</div>;
  return (
    <table>
      <thead>
        <tr><th>Symbol</th><th className="right">Qty</th><th className="right">Avg price</th><th className="right">Stop</th></tr>
      </thead>
      <tbody>
        {positions.map(([sym, p]) => (
          <tr key={sym}>
            <td>{sym}</td>
            <td className="right">{p.qty.toFixed(6)}</td>
            <td className="right">${p.avg_price.toFixed(2)}</td>
            <td className="right muted">${p.stop_price.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 5: Create `desktop/src/renderer/src/components/DecisionLog.tsx`**

```tsx
import type { Decision } from "../../../lib/parse";

export default function DecisionLog({ decisions }: { decisions: Decision[] }) {
  const recent = decisions.slice(-30).reverse();
  if (!recent.length) return <div className="empty">No decisions logged yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>Reason</th></tr>
      </thead>
      <tbody>
        {recent.map((d, i) => (
          <tr key={i}>
            <td className="muted">{new Date(d.ts).toLocaleTimeString()}</td>
            <td>{d.symbol}</td>
            <td><span className={`badge ${d.action}`}>{d.action}{d.executed ? "" : "*"}</span></td>
            <td>${d.price.toFixed(2)}</td>
            <td className="muted">{d.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 6: Overwrite `desktop/src/renderer/src/App.tsx`** (poll IPC every 5s)

```tsx
import { useEffect, useState } from "react";
import type { Snapshot } from "../../lib/parse";
import EquityChart from "./components/EquityChart";
import PositionsTable from "./components/PositionsTable";
import DecisionLog from "./components/DecisionLog";

const EMPTY: Snapshot = { state: null, trades: [], decisions: [] };
const api = (window as unknown as { api: { getSnapshot: () => Promise<Snapshot> } }).api;

export default function App(): React.JSX.Element {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);

  useEffect(() => {
    let alive = true;
    const load = async (): Promise<void> => {
      try {
        const s = await api.getSnapshot();
        if (alive) setSnap(s);
      } catch {
        /* keep last good snapshot */
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const cash = snap.state?.cash ?? 0;
  const eq = snap.state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = 10000; // display baseline; matches default paper_capital
  const pnl = equity - start;

  return (
    <main className="wrap">
      <div className="title">Crypto Paper-Trading Bot</div>
      <div className="sub">Read-only · polls every 5s · {snap.trades.length} trades logged</div>

      <div className="grid">
        <div className="card span2">
          <h2>Account</h2>
          <div className="kpis">
            <div className="kpi"><div className="label">Equity</div><div className="value">${equity.toFixed(2)}</div></div>
            <div className="kpi"><div className="label">Cash</div><div className="value">${cash.toFixed(2)}</div></div>
            <div className="kpi"><div className="label">P&amp;L</div>
              <div className="value" style={{ color: pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
              </div>
            </div>
          </div>
        </div>

        <div className="card span2">
          <h2>Equity curve</h2>
          <EquityChart history={eq ?? []} />
        </div>

        <div className="card">
          <h2>Open positions</h2>
          <PositionsTable state={snap.state} />
        </div>

        <div className="card">
          <h2>Decisions <span className="muted" style={{ textTransform: "none", letterSpacing: 0 }}>(* = not executed)</span></h2>
          <DecisionLog decisions={snap.decisions} />
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Verify the build**

Run: `cd desktop && npm run build`
Expected: builds with no type errors (renderer compiles App + components; `window.api` cast resolves).

- [ ] **Step 8: Commit**

```bash
git add desktop/src/renderer/src
git commit -m "feat(desktop): dark/glass renderer — equity chart, positions, decision log (5s IPC poll)"
```

---

### Task 6: Seed data, launch + Playwright visual verification, README

**Files:**
- Create: `desktop/README.md`

**Interfaces:** none (verification + docs).

- [ ] **Step 1: Seed `data/` with real bot output** (from repo root; no key needed — fail-safe HOLD still records prices + decisions; several cycles populate the equity curve)

```bash
for i in 1 2 3 4 5; do env -u MYHERMES_API_KEY .venv/bin/python -m engine.bot; done
```
Expected: `data/state.json` (equity_history with ≥5 points), `data/decisions.jsonl` (HOLD rows with real prices).

- [ ] **Step 2: Launch the Electron app in dev**

```bash
cd desktop && npm run dev
```
Expected: an Electron window opens showing the dashboard. (On a headless Linux box, wrap with `xvfb-run -a npm run dev` and screenshot via the renderer dev URL printed in the console.)

- [ ] **Step 3: Visual verification (controller-run)**

Confirm in the running app (or via a Playwright screenshot of the renderer dev URL / an `_electron` launch): the dark/glass theme renders; the Account card shows Equity/Cash/P&L; the equity-curve card draws the seeded points; Open positions shows "Flat" (or rows if a buy occurred); the Decisions panel lists recent HOLD rows with real prices and the `*` not-executed marker. No renderer console errors. Resize the window narrow (~400px) and wide (~1280px) and confirm the grid reflows (single column → two columns) without overflow. Fix any issue and re-verify before reporting done.

- [ ] **Step 4: Write `desktop/README.md`**

````markdown
# Crypto Bot Dashboard (Electron)

Read-only Electron desktop app for the paper-trading engine. The main process
reads the engine's `data/{state.json,trades.csv,decisions.jsonl}`; the renderer
polls it over IPC every 5s. It never writes or trades.

## Run (dev)
```bash
cd desktop
npm install
npm run dev
```
Reads `../data` by default. Override with `DATA_DIR=/abs/path npm run dev`.
Keep the bot's cron running and the window updates on its own.

## Build
```bash
npm run build       # bundles main + preload + renderer into out/
npm run start       # preview the built app
```
Packaging to an installer (electron-builder: AppImage/dmg/exe) is a follow-up;
when packaged, set `DATA_DIR` so it can find the engine's data dir.

## Test (pure parse/read layer)
```bash
npm test
```
````

- [ ] **Step 5: Commit**

```bash
git add desktop/README.md
git commit -m "docs(desktop): run instructions + verified dark/glass render"
```

---

## Self-Review

- **Spec coverage:** Electron desktop dashboard ✓ · dark/gradient/glass aesthetic ✓ (Task 5 index.css) · read-only, decoupled (main reads `data/`, renderer gets data only via IPC, no engine import, no fs in renderer) ✓ (Global Constraints, Task 4) · equity curve ✓ (EquityChart) · open positions ✓ (PositionsTable) · decision log with reasoning ✓ (Task 1 persists decisions → DecisionLog) · polled refresh ✓ (Task 5, 5s IPC poll) · tolerant of missing files ✓ (Task 4 `readOr`). The decision-log-with-reasoning requirement drove the Task 1 engine addition (the engine previously persisted only fills, not reasoning).
- **Placeholder scan:** every code step has complete code; commands have expected output; no TBD/TODO. The only non-verbatim step is Task 2 (the electron-vite scaffold generates files) — followed immediately by a build check, and the files this plan depends on (main, preload, renderer entry) are explicitly OVERWRITTEN with full content in Tasks 4–5, so scaffold variance can't break later tasks.
- **Type consistency:** `Snapshot`/`State`/`Trade`/`Decision`/`EquityPoint`/`Position` defined once in `parse.ts` (Task 3) and imported by `snapshot.ts` (Task 4), `App.tsx`, and all three components (Task 5). `readSnapshot(dir)` / `dataDir()` signatures match between `snapshot.ts` and `main/index.ts`. The preload exposes `getSnapshot(): Promise<Snapshot>`; `App.tsx` casts `window.api` to exactly that shape. The Python decision record in Task 1 (`ts,symbol,action,reason,price,executed`) matches the TS `Decision` type field-for-field.
- **Deliberate choices (noted):** Electron main is the only fs touchpoint (renderer stays sandbox-safe, types-only import of `parse.ts`); hand-written CSS over a UI kit (small, version-independent dark/glass); decisions stored append-only as JSONL, UI reads the last 30 (rotation is a later concern — noted, not built); `window.api` typed via a local cast in `App.tsx` rather than a global `.d.ts` (avoids depending on the scaffold's exact tsconfig include set); packaging to a distributable installer is explicitly deferred (v2) — v1 runs via `npm run dev` / `npm run start`.
