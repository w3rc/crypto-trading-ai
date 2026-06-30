# Symbol Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user add/remove trading pairs from the Settings page; the engine reads the list each cycle, and removing a pair that holds an open position is blocked.

**Architecture:** Mirror the engine's mode-override — a `data/symbols.json` override read by `config.py` (fails safe to `config.yaml`); `status.json` carries the effective symbol list. A Settings "Symbols" section edits the list (free-text validated add, ×-remove disabled when a position is open) and writes `symbols.json` over IPC.

**Tech Stack:** Python 3.14 engine (pytest); Electron + React + TypeScript, electron-vite, vitest (node env, `src/lib/**`). No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-06-30-symbol-manager-design.md`

## Global Constraints

- **No new dependencies.** Native inputs + Node/Python built-ins.
- **The symbols override is selection metadata only** — it never gates trading, and does NOT touch `create_order`, the mode/arm, or risk. NO change to the live-trading safety model.
- **vitest covers `src/lib/**` only.** `validSymbol`/`parseSymbols` get unit tests; `writeSymbols` (fs), the IPC, and the Settings UI are verified by `npm run build` + Playwright.
- **Pair format:** `^[A-Z0-9]+/[A-Z0-9]+$` (same regex in engine + lib). Override fails safe to `config.yaml` symbols. At least one symbol required to save.
- **Hermetic engine tests:** any test that constructs a config yaml MUST set `data_dir: {tmp_path}` (not the real `data/`) so overrides have no stray files to read.
- **Commit trailers** (every commit; verify with `git log --format="%B" -1 HEAD`, amend if missing):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine: `python -m pytest -q` (venv: `source .venv/bin/activate`). Desktop from `desktop/`: `npm test`, `npm run build`. Do NOT push.

---

### Task 1: Engine — `_symbols_override` + status carries `symbols`

**Files:**
- Modify: `engine/config.py` (add `import re`, `_symbols_override`, apply it)
- Modify: `engine/bot.py` (`_status_payload` writes `symbols`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `_symbols_override(data_dir: str, default: list[str]) -> list[str]` (valid non-empty `data/symbols.json` wins, else `default`); `status.json["symbols"]` = the effective list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_symbols_override_uses_valid_list(tmp_path):
    import json as _j
    from engine.config import _symbols_override
    (tmp_path / "symbols.json").write_text(_j.dumps(["SOL/USDT", "XRP/USDT"]))
    assert _symbols_override(str(tmp_path), ["BTC/USDT"]) == ["SOL/USDT", "XRP/USDT"]


def test_symbols_override_falls_back_to_default(tmp_path):
    from engine.config import _symbols_override
    d = ["BTC/USDT"]
    assert _symbols_override(str(tmp_path), d) == d                       # missing file
    (tmp_path / "symbols.json").write_text("{not json")
    assert _symbols_override(str(tmp_path), d) == d                       # corrupt
    (tmp_path / "symbols.json").write_text('{"a": 1}')
    assert _symbols_override(str(tmp_path), d) == d                       # not a list
    (tmp_path / "symbols.json").write_text('["btcusdt", "BTC-USDT", 5]')
    assert _symbols_override(str(tmp_path), d) == d                       # all invalid
    (tmp_path / "symbols.json").write_text("[]")
    assert _symbols_override(str(tmp_path), d) == d                       # empty


def test_status_payload_includes_symbols(tmp_path, monkeypatch):
    from engine.config import load_config
    from engine.bot import _status_payload
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT, ETH/USDT]\ntimeframe: 15m\n"
        f"paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: {tmp_path}\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert _status_payload(cfg, "t1", 0.0, None)["symbols"] == ["BTC/USDT", "ETH/USDT"]
```

- [ ] **Step 2: Run to verify failure**

Run: `source .venv/bin/activate && python -m pytest tests/test_config.py -k "symbols_override or status_payload_includes_symbols" -q`
Expected: FAIL — `_symbols_override` doesn't exist (ImportError) and `status` has no `"symbols"` key.

- [ ] **Step 3: Implement in `engine/config.py`**

Add `import re` to the imports at the top (the file currently imports `json`, `os`, … `yaml`):

```python
import re
```

Add this near `_mode_override` (e.g. just after it):

```python
_SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")


def _symbols_override(data_dir: str, default: list[str]) -> list[str]:
    """A valid non-empty symbols list in <data_dir>/symbols.json overrides config; fail-safe to default."""
    path = os.path.join(data_dir, "symbols.json")
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return default
    if not isinstance(raw, list):
        return default
    valid = [s for s in raw if isinstance(s, str) and _SYMBOL_RE.match(s)]
    return valid or default
```

Then change the `symbols=` line in `load_config` (currently `symbols=list(raw["symbols"]),`) to:

```python
        symbols=_symbols_override(raw["data_dir"], list(raw["symbols"])),
```

- [ ] **Step 4: Implement in `engine/bot.py`**

In `_status_payload`, add a `symbols` entry immediately after the `"interval_seconds": cfg.interval_seconds,` line:

```python
        "symbols": list(cfg.symbols),
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest -q`
Expected: PASS — the 3 new tests + all existing (238 → 241). (A valid `config.yaml` with no `symbols.json` present still yields its configured symbols, so existing config/bot tests are unaffected.)

- [ ] **Step 6: Commit**

```bash
git add engine/config.py engine/bot.py tests/test_config.py
git commit -m "feat(engine): symbols override (data/symbols.json) + status carries effective symbols"
```

---

### Task 2: Lib — `symbols.ts` helpers + `Status.symbols`

**Files:**
- Create: `desktop/src/lib/symbols.ts`
- Test: `desktop/src/lib/symbols.test.ts`
- Modify: `desktop/src/lib/parse.ts` (`Status` gains `symbols?: string[]`)

**Interfaces:**
- Produces: `validSymbol(s): boolean`; `parseSymbols(raw: unknown): string[]` (trim+uppercase, filter valid, dedupe); `writeSymbols(dir, symbols): Promise<string[]>` (throws if empty). `Status.symbols?: string[]`.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/lib/symbols.test.ts`:

```ts
import { test, expect } from "vitest";
import { validSymbol, parseSymbols } from "./symbols";

test("validSymbol accepts BASE/QUOTE uppercase, rejects the rest", () => {
  expect(validSymbol("BTC/USDT")).toBe(true);
  expect(validSymbol("SOL/USDT")).toBe(true);
  expect(validSymbol("btc/usdt")).toBe(false);
  expect(validSymbol("BTC-USDT")).toBe(false);
  expect(validSymbol("BTCUSDT")).toBe(false);
  expect(validSymbol("")).toBe(false);
});

test("parseSymbols uppercases, filters invalid, dedupes, drops non-strings", () => {
  expect(parseSymbols([" btc/usdt ", "ETH/USDT", "BTC/USDT", "bad", 5, "ETH/USDT"]))
    .toEqual(["BTC/USDT", "ETH/USDT"]);
  expect(parseSymbols("nope")).toEqual([]);
  expect(parseSymbols(null)).toEqual([]);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/symbols.test.ts`
Expected: FAIL — `./symbols` does not exist.

- [ ] **Step 3: Implement `desktop/src/lib/symbols.ts`**

```ts
import { writeFile, mkdir } from "fs/promises";
import { join } from "path";

const PAIR = /^[A-Z0-9]+\/[A-Z0-9]+$/;

export function validSymbol(s: string): boolean {
  return PAIR.test(s);
}

export function parseSymbols(raw: unknown): string[] {
  const list = Array.isArray(raw) ? raw : [];
  const out: string[] = [];
  for (const s of list) {
    if (typeof s !== "string") continue;
    const sym = s.trim().toUpperCase();
    if (validSymbol(sym) && !out.includes(sym)) out.push(sym);
  }
  return out;
}

export async function writeSymbols(dir: string, symbols: string[]): Promise<string[]> {
  const clean = parseSymbols(symbols);
  if (!clean.length) throw new Error("at least one symbol required");
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "symbols.json"), JSON.stringify(clean), "utf8");
  return clean;
}
```

- [ ] **Step 4: Add `symbols` to the `Status` type**

In `desktop/src/lib/parse.ts`, the `Status` type currently ends with `interval_seconds?: number; risk: RiskStatus; funding: FundingStatus };`. Add `symbols?: string[];` — e.g.:

```ts
export type Status = { ts: string; strategy: string; exchange: string; mode?: string; halted?: boolean; armed?: boolean;
                       interval_seconds?: number; symbols?: string[]; risk: RiskStatus; funding: FundingStatus };
```

- [ ] **Step 5: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS — 2 new tests + all existing (43 → 45).

- [ ] **Step 6: Commit**

```bash
git add desktop/src/lib/symbols.ts desktop/src/lib/symbols.test.ts desktop/src/lib/parse.ts
git commit -m "feat(dashboard): symbols lib (validSymbol/parseSymbols/writeSymbols) + Status.symbols"
```

---

### Task 3: Main — `set-symbols` IPC + preload (build-verified)

**Files:**
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts`

**Interfaces:**
- Consumes: `writeSymbols` (Task 2).
- Produces: IPC `set-symbols`; `window.api.setSymbols(list) => Promise<string[]>`.

- [ ] **Step 1: Add the IPC handler**

In `desktop/src/main/index.ts`, add the import near the other `../lib` imports:

```ts
import { writeSymbols } from "../lib/symbols";
```

Inside `app.whenReady().then(() => { ... })`, immediately after the existing `set-schedule` handler block, add:

```ts
    ipcMain.handle("set-symbols", (_e, list) => writeSymbols(dataDir(), list));
```

- [ ] **Step 2: Expose it in preload**

In `desktop/src/preload/index.ts`, add to the `api` object (keep all existing entries):

```ts
  setSymbols: (list: string[]) => ipcRenderer.invoke("set-symbols", list),
```

- [ ] **Step 3: Verify the build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(dashboard): set-symbols IPC + preload"
```

---

### Task 4: Renderer — Settings "Symbols" section + wiring + styles + gitignore (Playwright-verified)

**Files:**
- Modify: `desktop/src/renderer/src/components/Settings.tsx`
- Modify: `desktop/src/renderer/src/App.tsx` (pass `status` + `state`)
- Modify: `desktop/src/renderer/src/index.css`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `window.api.setSymbols` (Task 3); `validSymbol` (Task 2); `Status`/`State` (parse.ts).

- [ ] **Step 1: Replace `Settings.tsx` with the Symbols-enabled version**

Replace the entire contents of `desktop/src/renderer/src/components/Settings.tsx` with:

```tsx
import { useEffect, useState } from "react";
import type { Status, State } from "../../../lib/parse";
import { validSymbol } from "../../../lib/symbols";

type Schedule = { enabled: boolean; intervalSeconds: number };
type Result = { ok: boolean; stderrTail: string } | null;

const api = (window as unknown as {
  api: {
    runBot: () => Promise<{ ok: boolean; code: number | null; stderrTail: string }>;
    getSchedule: () => Promise<Schedule>;
    setSchedule: (s: Schedule) => Promise<Schedule>;
    setSymbols: (list: string[]) => Promise<string[]>;
  };
}).api;

export default function Settings({ status, state }: { status: Status | null; state: State | null }): React.JSX.Element {
  const [enabled, setEnabled] = useState(false);
  const [intervalSeconds, setIntervalSeconds] = useState(900);
  const [saved, setSaved] = useState<Schedule | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<Result>(null);
  const [saveMsg, setSaveMsg] = useState("");

  const [symbols, setSymbols] = useState<string[]>([]);
  const [symInput, setSymInput] = useState("");
  const [seeded, setSeeded] = useState(false);
  const [symMsg, setSymMsg] = useState("");

  useEffect(() => {
    api.getSchedule().then((s) => { setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s); });
  }, []);

  useEffect(() => {
    if (!seeded && status?.symbols) { setSymbols(status.symbols); setSeeded(true); }
  }, [status, seeded]);

  const save = async (): Promise<void> => {
    try {
      const s = await api.setSchedule({ enabled, intervalSeconds });
      setEnabled(s.enabled); setIntervalSeconds(s.intervalSeconds); setSaved(s); setSaveMsg("");
    } catch (err) {
      setSaveMsg(`Could not save schedule: ${String(err)}`);
    }
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

  const hasPosition = (sym: string): boolean => (state?.positions?.[sym]?.qty ?? 0) !== 0;

  const addSymbol = (): void => {
    const s = symInput.trim().toUpperCase();
    if (validSymbol(s) && !symbols.includes(s)) { setSymbols([...symbols, s]); setSymInput(""); setSymMsg(""); }
    else if (!validSymbol(s)) setSymMsg(`Not a valid pair: "${symInput}" (use BASE/QUOTE, e.g. SOL/USDT)`);
  };

  const removeSymbol = (s: string): void => {
    if (!hasPosition(s)) setSymbols(symbols.filter((x) => x !== s));
  };

  const saveSymbols = async (): Promise<void> => {
    try {
      setSymbols(await api.setSymbols(symbols));
      setSymMsg("");
    } catch (err) {
      setSymMsg(`Could not save symbols: ${String(err)}`);
    }
  };

  return (
    <div className="settings-form">
      <div className="settings-section-label">Trading pairs</div>
      <div className="symbol-chips">
        {symbols.map((s) => (
          <span className="symbol-chip" key={s}>
            {s}
            <button className="symbol-x" disabled={hasPosition(s)}
                    title={hasPosition(s) ? "close the position first" : "remove"}
                    onClick={() => removeSymbol(s)}>×</button>
          </span>
        ))}
      </div>
      <div className="settings-actions">
        <input className="symbol-input" placeholder="e.g. SOL/USDT" value={symInput}
               onChange={(e) => setSymInput(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") addSymbol(); }} />
        <button className="bt-run" onClick={addSymbol}>Add</button>
        <button className="bt-run" disabled={!symbols.length} onClick={saveSymbols}>Save symbols</button>
      </div>
      <div className="settings-summary">Each pair = one more LLM call per cycle; applies next cycle.</div>
      {symMsg && <div className="bt-result bt-error">{symMsg}</div>}

      <label className="settings-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Run the bot on a schedule (while this app is open)
      </label>
      <label className="settings-row">
        Interval (seconds)
        <input type="number" min={60} max={86400} value={intervalSeconds}
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
      {saveMsg && <div className="bt-result bt-error">{saveMsg}</div>}
      {result && result.ok && <div className="bt-result">Bot cycle complete — dashboard updating…</div>}
      {result && !result.ok && (
        <div className="bt-result bt-error">Bot run failed<pre>{result.stderrTail || "(no output)"}</pre></div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Pass `status` + `state` to Settings in `App.tsx`**

In `desktop/src/renderer/src/App.tsx`, change the settings render block (currently `<section className="card"><h2>Settings</h2><Settings /></section>`) to:

```tsx
        {view === "settings" && (
          <section className="card"><h2>Settings</h2><Settings status={snap.status} state={snap.state} /></section>
        )}
```

- [ ] **Step 3: Add styles**

Append to `desktop/src/renderer/src/index.css`:

```css
.settings-section-label { font-size: 14px; color: var(--text); }
.symbol-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.symbol-chip { display: inline-flex; align-items: center; gap: 6px; background: var(--glass);
  border: 1px solid var(--glass-border); border-radius: 999px; padding: 4px 6px 4px 12px; font-size: 13px; }
.symbol-x { background: none; border: none; color: var(--muted); font: inherit; font-size: 15px;
  line-height: 1; cursor: pointer; padding: 0 4px; }
.symbol-x:disabled { opacity: 0.35; cursor: not-allowed; }
.symbol-input { background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px;
  color: var(--text); font: inherit; padding: 7px 10px; width: 150px; }
```

- [ ] **Step 4: gitignore the runtime override**

In `.gitignore`, after the `data/scheduler.json` line, add:

```gitignore
data/symbols.json
```

- [ ] **Step 5: Build + full vitest**

Run: `cd desktop && npm test && npm run build`
Expected: vitest green (45, unchanged — no lib change here); build exit 0.

- [ ] **Step 6: Playwright verify (controller does this; 1280/768/375)**

Serve `desktop/out/renderer`; stub `window.api` with `getSchedule`/`setSchedule`/`runBot` plus `setSymbols: async (l) => l`, and a snapshot whose `status.symbols = ["BTC/USDT","ETH/USDT"]` and `state.positions = { "ETH/USDT": { qty: 1.29, ... } }`. On the Settings tab confirm:
- two chips render (BTC/USDT, ETH/USDT) from `status.symbols`;
- the **×** on ETH/USDT is **disabled** (has a position), BTC/USDT's is enabled;
- typing `SOL/USDT` + Add appends a third chip; an invalid add (`foo`) shows the "Not a valid pair" message and adds nothing;
- Save symbols calls `setSymbols`.

(Controller verification — the implementer completes Steps 1-5 and commits.)

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/src/components/Settings.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css .gitignore
git commit -m "feat(dashboard): Settings Symbols section — add/remove pairs, blocked while a position is open"
```

---

## Self-Review

**Spec coverage:**
- `_symbols_override` + status `symbols` → Task 1 ✓
- `validSymbol`/`parseSymbols`/`writeSymbols` + `Status.symbols` → Task 2 ✓
- `set-symbols` IPC + preload → Task 3 ✓
- Settings Symbols section (chips, free-text validated add, ×-disabled-when-position, Save min-1), App props, CSS, gitignore → Task 4 ✓
- Fail-safe override, never gates trading → Task 1 (`_symbols_override` returns `default` on any problem; only changes `cfg.symbols`) ✓
- Block removal when position open → Task 4 (`hasPosition` disables ×) ✓

**Placeholder scan:** none — every code step shows complete code or exact insertion text.

**Type consistency:**
- `validSymbol`/`parseSymbols`/`writeSymbols` defined Task 2, consumed in Task 3 (`writeSymbols`) and Task 4 (`validSymbol`) ✓
- `Status.symbols?: string[]` (Task 2) read by Settings' seed effect (Task 4) ✓
- IPC channel `"set-symbols"` matches main handler + preload + `window.api.setSymbols` ✓
- `_symbols_override(data_dir, default)` signature consistent between definition and the `load_config` call site (Task 1) ✓
