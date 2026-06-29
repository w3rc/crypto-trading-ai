# Ship-Resilience (Batch 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the prod-readiness resilience/safety gaps that don't need packaging: a corrupt `state.json` no longer wedges the bot silently, one torn `decisions.jsonl` line no longer blanks the dashboard log, a second app launch focuses the existing window, and runtime files are gitignored.

**Architecture:** Small, isolated hardening in three areas — engine state-load (fail-safe + money-safe), the dashboard's decisions parser (skip bad lines), and the Electron main process (single-instance). No feature changes.

**Tech Stack:** Python 3.14 engine (pytest); Electron + React + TypeScript, electron-vite, vitest (node env, `src/lib/**`).

**Source:** prod-readiness audit `.superpowers/sdd/prod-readiness-audit.md` items C4, C5, C2, C7. (C1 packaged-data-path is intentionally OUT — dev-local resolution already works via `DATA_DIR` → repo `../data`, and the shipped liveness "no data · is the bot running?" line already signals an empty dir.)

## Global Constraints

- **Money-safe state load (C4):** a corrupt/unreadable `state.json` must NOT silently reset the paper portfolio. Back the bad file up to `state.json.corrupt` and raise a clear error so the owner restores or deletes it deliberately. (The atomic writer makes self-corruption near-impossible; this guards external causes.)
- **No new dependencies.** No change to the live-trading safety model, the mode toggle, `create_order`, or the freshness/liveness behavior.
- **vitest covers `src/lib/**` only.** `parseDecisions` gets a unit test; the Electron main-process single-instance change is verified by `npm run build` (no component/main test).
- **Commit trailers** (every commit; verify with `git log --format="%B" -1 HEAD` after each, amend if missing):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q` (venv: `source .venv/bin/activate`). Desktop: from `desktop/` — `npm test`, `npm run build`. Do NOT push.

---

### Task 1: Engine — `load_state` corruption guard (money-safe)

**Files:**
- Modify: `engine/state.py` (`load_state`)
- Test: `tests/test_state.py` (add `import pytest`)

**Interfaces:**
- Produces: `load_state(data_dir, initial_capital, symbols)` — on a corrupt/unreadable/missing-key `state.json`, renames it to `state.json.corrupt` and raises `RuntimeError`; valid and missing-file behavior unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_state.py`, add `import pytest` to the imports at the top (the file currently imports `json as _json`, `engine.state`, `engine.models`). Then append:

```python
def test_load_state_corrupt_json_backs_up_and_raises(tmp_path):
    (tmp_path / "state.json").write_text("{not valid json")
    with pytest.raises(RuntimeError, match="corrupt"):
        load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    assert (tmp_path / "state.json.corrupt").exists()      # bad file preserved
    assert not (tmp_path / "state.json").exists()          # moved aside, not silently reset

def test_load_state_missing_required_key_backs_up_and_raises(tmp_path):
    (tmp_path / "state.json").write_text('{"positions": {}}')   # no "cash" key
    with pytest.raises(RuntimeError):
        load_state(str(tmp_path), 1000.0, [])
    assert (tmp_path / "state.json.corrupt").exists()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_state.py -k "corrupt or missing_required_key" -q`
Expected: FAIL — currently a corrupt file raises `json.JSONDecodeError` / `KeyError` (not `RuntimeError`) and no `.corrupt` backup is made.

- [ ] **Step 3: Implement**

In `engine/state.py`, replace the body of `load_state` after the `if not os.path.exists(path): return State(...)` block (i.e. the `with open(path) ... return State(...)` part) with a guarded version:

```python
    try:
        with open(path) as f:
            raw = json.load(f)
        positions = {s: Position(**{k: v for k, v in p.items() if k in _POS_FIELDS})
                     for s, p in raw["positions"].items()}
        cash = raw["cash"]
    except (json.JSONDecodeError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        corrupt = path + ".corrupt"
        os.replace(path, corrupt)            # preserve the bad file; never silently reset the portfolio
        raise RuntimeError(
            f"state.json is corrupt ({e}); backed up to {corrupt}. "
            f"Restore a good copy or delete it to start fresh."
        ) from e
    for s in symbols:                       # ensure newly-added symbols exist
        positions.setdefault(s, Position(s))
    return State(cash=cash, positions=positions,
                 equity_history=raw.get("equity_history", []),
                 last_funding_ts=raw.get("last_funding_ts"),
                 funding_accrued=raw.get("funding_accrued", 0.0))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest -q`
Expected: PASS — the 2 new tests + all existing (existing valid-load and round-trip tests still pass: a well-formed `state.json` takes the same path as before).

- [ ] **Step 5: Commit**

```bash
git add engine/state.py tests/test_state.py
git commit -m "fix: corrupt state.json backs up to .corrupt and fails loud (never silently resets the portfolio)"
```

---

### Task 2: Desktop lib — `parseDecisions` skips torn lines

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`parseDecisions`)
- Test: `desktop/src/lib/parse.test.ts`

**Interfaces:**
- Produces: `parseDecisions(text)` — JSON-parses each non-empty line, **skipping** any line that fails to parse (a half-written final line no longer discards the whole log).

- [ ] **Step 1: Write the failing test**

Append to `desktop/src/lib/parse.test.ts` (it already imports `parseDecisions`):

```ts
test("parseDecisions skips a torn line and keeps the rest", () => {
  const text = [
    JSON.stringify({ ts: "t1", symbol: "BTC/USDT", action: "hold", reason: "x", price: 1, executed: false }),
    '{"ts":"t2","symbol":"ETH',                       // torn / half-written line
    JSON.stringify({ ts: "t3", symbol: "ETH/USDT", action: "buy", reason: "y", price: 2, executed: true }),
  ].join("\n");
  const out = parseDecisions(text);
  expect(out.map((d) => d.ts)).toEqual(["t1", "t3"]);   // bad line skipped, others kept
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/parse.test.ts`
Expected: FAIL — the current `.map(JSON.parse)` throws on the torn line, so the test errors instead of returning 2 rows.

- [ ] **Step 3: Implement**

In `desktop/src/lib/parse.ts`, replace the `parseDecisions` function with:

```ts
export function parseDecisions(text: string): Decision[] {
  const out: Decision[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (t === "") continue;
    try {
      out.push(JSON.parse(t) as Decision);
    } catch {
      // skip a torn/partial line (e.g. process killed mid-append) — keep the rest
    }
  }
  return out;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS — the new test + existing parse tests.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/parse.test.ts
git commit -m "fix(dashboard): parseDecisions skips a torn jsonl line instead of blanking the whole log"
```

---

### Task 3: Single-instance lock + gitignore + docs

**Files:**
- Modify: `desktop/src/main/index.ts` (single-instance lock; track the window)
- Modify: `.gitignore` (runtime files)
- Modify: `README.md` (one-line note)
- Verify: `npm run build`

**Interfaces:**
- Consumes: nothing new. Main-process only; verified by build.

- [ ] **Step 1: Single-instance lock**

Replace the entire contents of `desktop/src/main/index.ts` with:

```ts
import { app, BrowserWindow, ipcMain } from "electron";
import { join } from "path";
import { is } from "@electron-toolkit/utils";
import { readSnapshot, dataDir } from "../lib/snapshot";
import { writeControl } from "../lib/control";

let mainWindow: BrowserWindow | null = null;

function createWindow(): void {
  mainWindow = new BrowserWindow({
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

  mainWindow.on("ready-to-show", () => mainWindow?.show());

  if (is.dev && process.env["ELECTRON_RENDERER_URL"]) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"]);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();                                   // a second launch hands off to the running one
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    ipcMain.handle("snapshot", () => readSnapshot(dataDir()));
    ipcMain.handle("set-mode", (_e, mode: string) => writeControl(dataDir(), mode));
    createWindow();
    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
```

- [ ] **Step 2: gitignore the runtime files**

In `.gitignore`, after the existing `data/decisions.jsonl` line, add the runtime files the bot writes that aren't yet ignored:

```gitignore
data/status.json
data/control.json
data/live_meta.json
data/HALT
```

(If any of these are already tracked, that's out of scope — just add the ignore lines.)

- [ ] **Step 3: README note**

In `README.md`, near where the dashboard / running notes live, add a short line:

```markdown
The desktop app is single-instance (a second launch focuses the running window). Runtime files in
`data/` (`state.json`, `status.json`, `control.json`, `live_meta.json`, `HALT`, …) are gitignored — a
corrupt `state.json` is backed up to `state.json.corrupt` and the bot stops loudly rather than resetting.
```

- [ ] **Step 4: Build + full suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest green; build exit 0.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/index.ts .gitignore README.md
git commit -m "feat(dashboard): single-instance lock; gitignore runtime files; document resilience"
```

---

## Self-Review

**Spec coverage:**
- C4 corrupt `state.json` → back up + fail loud (money-safe) → Task 1 ✓
- C5 torn `decisions.jsonl` line skipped → Task 2 ✓
- C2 single-instance lock → Task 3 Step 1 ✓
- C7 gitignore runtime files → Task 3 Step 2 ✓
- C1 intentionally out (dev-local) → documented in the plan intro ✓

**Placeholder scan:** none — every code step shows full code or exact insertion text.

**Type/signature consistency:**
- `load_state(data_dir, initial_capital, symbols)` signature unchanged; only failure behavior added — Task 1 ✓
- `parseDecisions(text) -> Decision[]` signature unchanged — Task 2 ✓
- `createWindow` now assigns a module-level `mainWindow`; IPC handlers unchanged inside `whenReady` — Task 3 ✓
