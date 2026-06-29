# Sidebar Mode Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `[ Paper | Shadow | Live ]` toggle at the bottom of the dashboard rail that changes the bot's mode via a `data/control.json` override the engine reads — while `LIVE_TRADING_ARMED` stays the operator-only money-gate, so a click alone can never place real orders.

**Architecture:** The renderer writes `data/control.json` through a new `setMode` IPC; `engine/config.py` reads it as a mode override (fail-safe). The bot's status gains `armed` so the rail honestly shows LIVE (armed) vs LIVE · UNARMED (configured live but running shadow). The existing `_live_armed()` routing is untouched.

**Tech Stack:** Python 3.14 engine (pytest); Electron + React + TypeScript, electron-vite, vitest (node env, `src/lib/**`).

## Global Constraints

- **Safety invariant (do not weaken):** `mode == "live"` places real orders ONLY when `_live_armed()` (env `LIVE_TRADING_ARMED == "yes"`). The toggle changes only how `mode` is *sourced* (control.json vs config.yaml); it never touches the env gate. control.json `live` + unarmed ⇒ the bot runs shadow, no `create_order`. This is tested.
- **Valid modes are exactly `paper`, `shadow`, `live`.** The writer rejects anything else; the engine override ignores anything else.
- **Engine override is fail-safe:** missing / unreadable / bad-JSON / out-of-set `control.json` ⇒ keep the `config.yaml` mode; never raise.
- **vitest covers `src/lib/**` only.** `control.ts` and `modeBadge` get unit tests; the IPC (main/preload) and the Sidebar are verified by `npm run build` + controller Playwright (no component tests).
- **No new dependencies.**
- **Commit trailers** (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q` (venv: `source .venv/bin/activate`). Desktop: from `desktop/` — `npm test`, `npm run build`.
- Full design: `docs/superpowers/specs/2026-06-29-sidebar-mode-toggle-design.md`.

---

### Task 1: Engine — `control.json` mode override in `load_config`

**Files:**
- Modify: `engine/config.py` (add `import json`; `_mode_override` helper; use it for `mode`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config` returns `Config.mode` = a valid mode from `<data_dir>/control.json` if present, else the `config.yaml` `mode` (default `paper`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def _toggle_yaml(data_dir, mode="paper"):
    return (
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\n"
        f"data_dir: {data_dir}\nmode: {mode}\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )

def test_control_json_overrides_mode(tmp_path):
    (tmp_path / "control.json").write_text('{"mode": "live"}')
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper"))
    assert load_config(str(p)).mode == "live"          # control.json wins over config

def test_control_json_invalid_mode_ignored(tmp_path):
    (tmp_path / "control.json").write_text('{"mode": "bogus"}')
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "shadow"))
    assert load_config(str(p)).mode == "shadow"        # invalid -> config mode

def test_control_json_missing_uses_config(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "shadow"))
    assert load_config(str(p)).mode == "shadow"        # no control.json -> config mode

def test_control_json_corrupt_ignored(tmp_path):
    (tmp_path / "control.json").write_text("{not json")
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper"))
    assert load_config(str(p)).mode == "paper"         # corrupt -> config mode
```

(`load_config` resolves the LLM key via `os.environ.get(..., "")`, so no env is needed for these.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_config.py -k control_json -q`
Expected: FAIL — `test_control_json_overrides_mode` (mode stays `paper`); the others may pass incidentally.

- [ ] **Step 3: Implement**

In `engine/config.py`, add `import json` at the top (with the other stdlib imports). Add the helper above `load_config`:

```python
_VALID_MODES = {"paper", "shadow", "live"}


def _mode_override(data_dir: str, default: str) -> str:
    """A valid mode in <data_dir>/control.json overrides the config mode; fail-safe to default."""
    path = os.path.join(data_dir, "control.json")
    try:
        with open(path) as f:
            m = json.load(f).get("mode")
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return default                      # missing / unreadable / bad JSON / non-dict -> config mode
    return m if m in _VALID_MODES else default
```

In `load_config`, replace the `mode=` line in the `Config(...)` construction:

```python
        mode=_mode_override(raw["data_dir"], raw.get("mode", "paper")),
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/config.py tests/test_config.py
git commit -m "feat: mode override via data/control.json (fail-safe to config)"
```

---

### Task 2: Engine — `armed` in the status payload

**Files:**
- Modify: `engine/bot.py` (`_status_payload` adds `"armed"`)
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `_live_armed()` (already defined in `engine/bot.py`).
- Produces: `status.json` gains a top-level `"armed": bool`. All existing `_status_payload` call sites get it automatically (it is computed inside, not a parameter).

**Note (safety composition):** the spec's "control.json `live` + unarmed ⇒ shadow, no `create_order`" is the composition of Task 1 (override → `mode="live"`) and the existing, unchanged `test_live_unarmed_falls_back_to_shadow` (mode live + unarmed → `_run_shadow`, no order). No new routing test is needed here; this task adds the `armed` signal the dashboard reads.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
def test_status_carries_armed_true(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path)                                  # paper mode
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["armed"] is True

def test_status_carries_armed_false(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ARMED", raising=False)
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["armed"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bot.py -k "status_carries_armed" -q`
Expected: FAIL — `KeyError: 'armed'`.

- [ ] **Step 3: Implement**

In `engine/bot.py` `_status_payload`, add the `"armed"` field (right after `"halted"`):

```python
def _status_payload(cfg, ts, funding_accrued, last_funding_ts, halted=False):
    return {
        "ts": ts,
        "mode": cfg.mode,
        "halted": halted,
        "armed": _live_armed(),
        "strategy": cfg.strategy,
        "exchange": cfg.exchange,
        "risk": {
            "allow_short": bool(cfg.risk.allow_short),
            "leverage": cfg.risk.leverage,
            "maintenance_margin_pct": cfg.risk.maintenance_margin_pct,
            "funding_rate": cfg.risk.funding_rate,
            "funding_interval_hours": cfg.risk.funding_interval_hours,
            "max_position_pct": cfg.risk.max_position_pct,
            "stop_loss_pct": cfg.risk.stop_loss_pct,
        },
        "funding": {"accrued": funding_accrued, "last_funding_ts": last_funding_ts},
    }
```

- [ ] **Step 4: Run the engine suite**

Run: `python -m pytest -q`
Expected: PASS — new + all existing (the extra status field breaks nothing).

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat: status.json carries armed (env LIVE_TRADING_ARMED) for honest UI"
```

---

### Task 3: Desktop write-path — `control.ts` writer + `setMode` IPC

**Files:**
- Create: `desktop/src/lib/control.ts`
- Test: `desktop/src/lib/control.test.ts`
- Modify: `desktop/src/main/index.ts` (register `set-mode`)
- Modify: `desktop/src/preload/index.ts` (expose `setMode`)

**Interfaces:**
- Produces: `writeControl(dir: string, mode: string): Promise<void>` — writes `<dir>/control.json` = `{ mode }` for valid modes; throws for invalid (writes nothing). Renderer gains `window.api.setMode(mode: string): Promise<void>`.

- [ ] **Step 1: Write the failing test**

Create `desktop/src/lib/control.test.ts`:

```ts
import { test, expect } from "vitest";
import { writeControl } from "./control";
import { mkdtempSync, readFileSync, existsSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

test("writeControl writes {mode} for valid modes", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "shadow");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ mode: "shadow" });
});

test("writeControl rejects an invalid mode and writes nothing", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await expect(writeControl(d, "bogus")).rejects.toThrow();
  expect(existsSync(join(d, "control.json"))).toBe(false);
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/control.test.ts`
Expected: FAIL — `./control` does not exist.

- [ ] **Step 3: Implement the writer**

Create `desktop/src/lib/control.ts`:

```ts
import { writeFile, mkdir } from "fs/promises";
import { join } from "path";

const VALID = new Set(["paper", "shadow", "live"]);

export async function writeControl(dir: string, mode: string): Promise<void> {
  if (!VALID.has(mode)) throw new Error(`invalid mode: ${mode}`);
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "control.json"), JSON.stringify({ mode }), "utf8");
}
```

- [ ] **Step 4: Wire the IPC**

In `desktop/src/main/index.ts`, add the import (next to the snapshot import) and the handler (next to the `snapshot` handler):

```ts
import { writeControl } from "../lib/control";
```
```ts
  ipcMain.handle("set-mode", (_e, mode: string) => writeControl(dataDir(), mode));
```

In `desktop/src/preload/index.ts`, add `setMode` to the `api` object:

```ts
const api = {
  getSnapshot: () => ipcRenderer.invoke("snapshot"),
  setMode: (mode: string) => ipcRenderer.invoke("set-mode", mode),
};
```

- [ ] **Step 5: Verify**

Run: `cd desktop && npm test && npm run build`
Expected: vitest PASS (control tests + existing); build exit 0.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/lib/control.ts desktop/src/lib/control.test.ts desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(dashboard): control.json writer + setMode IPC (validated write path)"
```

---

### Task 4: Desktop — `modeBadge` gains `armed`; `Status.armed`

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`Status` gains `armed?`)
- Modify: `desktop/src/lib/status.ts` (`modeBadge` third arg + `live-unarmed` tone)
- Test: `desktop/src/lib/status.test.ts` (replace the existing `modeBadge` tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `modeBadge(mode?: string, halted?: boolean, armed?: boolean) -> { label: string; tone: ModeTone }` with `ModeTone = "live" | "live-unarmed" | "shadow" | "paper" | "halted"`. `Status` gains `armed?: boolean`.

- [ ] **Step 1: Replace the failing tests**

In `desktop/src/lib/status.test.ts`, REPLACE the two existing `modeBadge` tests (the `test("modeBadge maps mode to tone+label", ...)` and `test("modeBadge: halted overrides every mode", ...)` blocks) with:

```ts
test("modeBadge maps mode+armed to tone+label", () => {
  expect(modeBadge("paper", false, false)).toEqual({ label: "PAPER", tone: "paper" });
  expect(modeBadge("shadow", false, false)).toEqual({ label: "SHADOW", tone: "shadow" });
  expect(modeBadge("live", false, true)).toEqual({ label: "LIVE", tone: "live" });
  expect(modeBadge("live", false, false)).toEqual({ label: "LIVE · UNARMED", tone: "live-unarmed" });
  expect(modeBadge(undefined, false, false)).toEqual({ label: "PAPER", tone: "paper" });
});

test("modeBadge: halted overrides every mode", () => {
  expect(modeBadge("live", true, true)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge("paper", true, false)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge("shadow", true, false)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge(undefined, true, false)).toEqual({ label: "HALTED", tone: "halted" });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/status.test.ts`
Expected: FAIL — `modeBadge("live", false, false)` currently returns `{label:"LIVE",tone:"live"}`, not the unarmed variant.

- [ ] **Step 3: Implement**

In `desktop/src/lib/parse.ts`, add `armed?: boolean` to the `Status` type:

```typescript
export type Status = { ts: string; strategy: string; exchange: string; mode?: string; halted?: boolean; armed?: boolean;
                       risk: RiskStatus; funding: FundingStatus };
```

In `desktop/src/lib/status.ts`, replace the `ModeTone` type and `modeBadge` function with:

```ts
export type ModeTone = "live" | "live-unarmed" | "shadow" | "paper" | "halted";

export function modeBadge(mode?: string, halted?: boolean, armed?: boolean): { label: string; tone: ModeTone } {
  if (halted) return { label: "HALTED", tone: "halted" };
  if (mode === "live") return armed ? { label: "LIVE", tone: "live" } : { label: "LIVE · UNARMED", tone: "live-unarmed" };
  if (mode === "shadow") return { label: "SHADOW", tone: "shadow" };
  return { label: "PAPER", tone: "paper" };
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS (the `modeBadge` matrix + existing helpers).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/status.ts desktop/src/lib/status.test.ts
git commit -m "feat(dashboard): modeBadge armed dimension (LIVE vs LIVE · UNARMED) + Status.armed"
```

---

### Task 5: Desktop — the rail mode toggle (Sidebar)

**Files:**
- Modify: `desktop/src/renderer/src/components/Sidebar.tsx` (toggle + confirm + optimistic pending; badge passes `armed`; footer wording)
- Modify: `desktop/src/renderer/src/index.css` (segment control + `.mode-live-unarmed`; live filled vs unarmed outline; responsive)

**Interfaces:**
- Consumes: `modeBadge(mode, halted, armed)` (Task 4); `window.api.setMode` (Task 3); `Status.armed` (Task 4).

- [ ] **Step 1: Update the Sidebar**

Replace the entire contents of `desktop/src/renderer/src/components/Sidebar.tsx` with:

```tsx
import { useState, useEffect } from "react";
import type { State, Status } from "../../../lib/parse";
import { modeBadge } from "../../../lib/status";

export type View = "overview" | "positions" | "activity" | "sentiment" | "backtest";

const NAV: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "positions", label: "Positions" },
  { id: "activity", label: "Activity" },
  { id: "sentiment", label: "Sentiment" },
  { id: "backtest", label: "Backtest" },
];

const MODES: { id: string; label: string }[] = [
  { id: "paper", label: "Paper" },
  { id: "shadow", label: "Shadow" },
  { id: "live", label: "Live" },
];

const api = (window as unknown as { api: { setMode?: (m: string) => Promise<void> } }).api;

export default function Sidebar({ status, state, view, onNavigate }: {
  status: Status | null;
  state: State | null;
  view: View;
  onNavigate: (v: View) => void;
}) {
  const badge = modeBadge(status?.mode, status?.halted, status?.armed);
  const cash = state?.cash ?? 0;
  const eq = state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : equity;
  const pnl = equity - start;

  const current = status?.mode ?? "paper";
  const [pending, setPending] = useState<string | null>(null);
  useEffect(() => {
    if (pending && status?.mode === pending) setPending(null);   // bot caught up -> clear hint
  }, [status?.mode, pending]);
  const activeMode = pending ?? current;

  const choose = (m: string): void => {
    if (m === activeMode) return;
    if (m === "live" &&
        !window.confirm("Switch bot to LIVE mode? Real orders place only if LIVE_TRADING_ARMED=yes is set in the bot's env.")) {
      return;
    }
    setPending(m);
    void api?.setMode?.(m).catch(() => setPending(null));        // failed write -> drop optimistic state
  };

  return (
    <aside className="sidebar">
      <div className="brand">Crypto Trading Bot</div>

      <div className={`mode-badge mode-${badge.tone}`}>
        <span className="mode-dot" />
        {badge.label}
      </div>

      <div className="rail-acct">
        <div className="rail-eq">${equity.toFixed(2)}</div>
        <div className="rail-pnl" style={{ color: pnl >= 0 ? "var(--up)" : "var(--down)" }}>
          {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
        </div>
      </div>

      <nav className="rail-nav">
        {NAV.map((n) => (
          <button
            key={n.id}
            className={`rail-link ${view === n.id ? "active" : ""}`}
            onClick={() => onNavigate(n.id)}
          >
            {n.label}
          </button>
        ))}
      </nav>

      <div className="rail-toggle">
        <div className="rail-toggle-label">Mode</div>
        <div className="seg">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={`seg-btn ${activeMode === m.id ? "active" : ""}`}
              onClick={() => choose(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        {pending && pending !== current && <div className="rail-toggle-hint">applies next cycle</div>}
      </div>

      <div className="rail-foot">
        {status ? `${status.exchange} · ${status.strategy}` : "—"}
        <br />
        polls 5s
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Update the CSS**

In `desktop/src/renderer/src/index.css`: (a) make armed LIVE a filled amber chip (distinct from the unarmed outline), (b) add the `.mode-live-unarmed` tone, (c) add the segment control, (d) move the bottom anchor from the footer to the toggle group.

Change the existing `.mode-live` rule to add a fill:
```css
.mode-live { color: var(--mode-live); background: rgba(245,158,11,0.15); }
```
Change `.rail-foot` to drop `margin-top: auto`:
```css
.rail-foot { color: var(--muted); font-size: 12px; line-height: 1.6; }
```
Append:
```css
.mode-live-unarmed { color: var(--mode-live); }   /* outline only — configured live but running shadow */
.rail-toggle { margin-top: auto; }
.rail-toggle-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }
.seg { display: flex; gap: 2px; padding: 2px; background: var(--glass); border: 1px solid var(--glass-border); border-radius: 8px; }
.seg-btn { flex: 1; background: none; border: none; color: var(--muted); font: inherit; font-size: 12px; padding: 6px 4px; border-radius: 6px; cursor: pointer; }
.seg-btn:hover { color: var(--text); }
.seg-btn.active { background: var(--accent); color: #0a0e1a; font-weight: 600; }
.rail-toggle-hint { color: var(--muted); font-size: 11px; margin-top: 6px; }
@media (max-width: 820px) { .rail-toggle { margin-top: 0; } }
```

- [ ] **Step 3: Build + test**

Run: `cd desktop && npm test && npm run build`
Expected: vitest unchanged-green; build exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/Sidebar.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): rail mode toggle (paper/shadow/live, confirm-on-live, armed display)"
```

---

### Task 6: README + final verification

**Files:**
- Modify: `README.md`
- Verify: build + controller Playwright

- [ ] **Step 1: Update the README**

In `README.md`, in the dashboard description (the nav-sidebar paragraph added by the redesign), add a sentence about the toggle:

```markdown
The sidebar also has a **mode toggle** (Paper / Shadow / Live) that writes `data/control.json`, which
the engine reads as a mode override on its next cycle (switching to **Live** asks for confirmation).
Live still requires `LIVE_TRADING_ARMED=yes` in the bot's env to place real orders — the toggle alone
runs **shadow** when unarmed, shown as `LIVE · UNARMED` in the rail.
```

- [ ] **Step 2: Full suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest green; build exit 0.

- [ ] **Step 3: Playwright visual verification (CONTROLLER-RUN)**

The controller renders the real `App` via a harness stubbing `window.api.getSnapshot` (status with `mode`/`halted`/`armed`) **and** `window.api.setMode`, then verifies at 1280/768/375: the toggle renders at the rail bottom; clicking Shadow/Paper moves the active segment; clicking Live raises the confirm; the rail badge shows LIVE (armed) vs LIVE · UNARMED (mode live, armed false) vs SHADOW/PAPER, and HALTED overrides. Clean up harness artifacts. (Controller step, not the task subagent.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the dashboard mode toggle (control.json, env still gates live)"
```

---

## Self-Review

**Spec coverage:**
- control.json override read (fail-safe) → Task 1 ✓
- `armed` in status → Task 2 ✓
- control writer (validated) + `setMode` IPC → Task 3 ✓
- `modeBadge(armed)` + `live-unarmed` tone + `Status.armed` → Task 4 ✓
- rail toggle (segments, confirm-on-live, optimistic pending, honest badge) + CSS → Task 5 ✓
- safety: control.json `live` + unarmed ⇒ shadow/no order → Task 1 (override→live) + existing `test_live_unarmed_falls_back_to_shadow` (noted in Task 2) ✓
- README + Playwright → Task 6 ✓
- valid modes only / no env change from UI / no new deps → Global Constraints; Task 3 writer rejects invalid; nothing touches the env gate ✓

**Placeholder scan:** none — every code step shows full code or exact insertion/replacement text.

**Type/signature consistency:**
- `_mode_override(data_dir, default) -> str` — Task 1 defines + uses ✓
- `_status_payload` adds `"armed": _live_armed()` (computed inside; call sites unchanged) — Task 2 ✓
- `writeControl(dir, mode) -> Promise<void>` — Task 3 defines (lib), main IPC + preload `setMode` consume ✓
- `modeBadge(mode?, halted?, armed?) -> {label, tone}`, `ModeTone` adds `"live-unarmed"` — Task 4 defines, Task 5 Sidebar calls `modeBadge(status?.mode, status?.halted, status?.armed)` ✓
- `Status.armed?` — Task 4 (parse) defines, Task 5 consumes ✓
- `window.api.setMode` — Task 3 (preload) defines, Task 5 calls ✓
- `View`/`Sidebar` props unchanged from the redesign (Task 5 keeps the same signature) ✓
```
