# Dashboard Liveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dashboard honest about whether the bot is alive, fresh, and thinking — a freshness/"bot stopped" signal, a brain-health chip, and a collapsed decision log.

**Architecture:** The engine stamps a declared cron cadence (`interval_seconds`) into `status.json`; the dashboard derives data age from `status.ts` and flags STALE past 2.5× that cadence. Brain health and the log collapse are pure dashboard derivations from the existing decision reasons. No change to the live-trading safety model.

**Tech Stack:** Python 3.14 engine (pytest); Electron + React + TypeScript, electron-vite, vitest (node env, `src/lib/**`).

## Global Constraints

- **No change to the live-trading safety model, the mode toggle, or `create_order`.** `interval_seconds` is display-only metadata; it never gates trading.
- **Backward compatible:** `interval_seconds` is optional everywhere; an old `status.json` without it must still render (dashboard falls back to 900s).
- **vitest covers `src/lib/**` only.** The new helpers (`freshness`, `brainHealth`) get unit tests; the Sidebar and DecisionLog are verified by `npm run build` + controller Playwright (no component tests).
- **No new dependencies.**
- **Commit trailers** (every commit, verify with `git log --format="%B" -1 HEAD` after each commit; amend if missing):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q` (venv: `source .venv/bin/activate`). Desktop: from `desktop/` — `npm test`, `npm run build`. Do NOT push.
- Full design: `docs/superpowers/specs/2026-06-29-dashboard-liveness-design.md`.

---

### Task 1: Engine — `interval_seconds` in config

**Files:**
- Modify: `engine/config.py` (`Config` dataclass + `load_config`)
- Modify: `engine/config.yaml` (documented line)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.interval_seconds: int` — from `config.yaml` `interval_seconds`, default `900`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py` (reuses the existing `_toggle_yaml` helper in that file):

```python
def test_interval_seconds_defaults_to_900(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper"))
    assert load_config(str(p)).interval_seconds == 900     # absent -> default

def test_interval_seconds_from_yaml(tmp_path):
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path, "paper") + "interval_seconds: 300\n")
    assert load_config(str(p)).interval_seconds == 300     # yaml value wins
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_config.py -k interval_seconds -q`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'interval_seconds'`.

- [ ] **Step 3: Implement**

In `engine/config.py`, add the field to the `Config` dataclass, immediately after the `mode: str = "paper"` line:

```python
    mode: str = "paper"
    interval_seconds: int = 900
```

In `load_config`, in the `Config(...)` construction, add immediately after the `mode=...` line:

```python
        interval_seconds=int(raw.get("interval_seconds", 900)),
```

- [ ] **Step 4: Document in config.yaml**

In `engine/config.yaml`, add a top-level line near `mode:` (anywhere at the top level is fine):

```yaml
interval_seconds: 900  # seconds between cron cycles; the dashboard flags STALE past ~2.5x this
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS (new + existing).

- [ ] **Step 6: Commit**

```bash
git add engine/config.py engine/config.yaml tests/test_config.py
git commit -m "feat: config interval_seconds (declared cron cadence, default 900)"
```

---

### Task 2: Engine — `interval_seconds` in the status payload

**Files:**
- Modify: `engine/bot.py` (`_status_payload`)
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `Config.interval_seconds` (Task 1).
- Produces: `status.json` gains a top-level `"interval_seconds": int`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bot.py` (reuses the existing `_cfg`, `FakeMarket`, `_strat`, `_json` helpers):

```python
def test_status_carries_interval_seconds(tmp_path):
    cfg = _cfg(tmp_path)                                   # Config default interval_seconds == 900
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["interval_seconds"] == 900
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bot.py -k status_carries_interval_seconds -q`
Expected: FAIL — `KeyError: 'interval_seconds'`.

- [ ] **Step 3: Implement**

In `engine/bot.py` `_status_payload`, add the field immediately after the `"armed": _live_armed(),` line:

```python
        "armed": _live_armed(),
        "interval_seconds": cfg.interval_seconds,
```

- [ ] **Step 4: Run the engine suite**

Run: `python -m pytest -q`
Expected: PASS — new + all existing.

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat: status.json carries interval_seconds for the dashboard staleness check"
```

---

### Task 3: Desktop lib — `freshness` + `brainHealth` helpers

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`Status` gains `interval_seconds?`)
- Modify: `desktop/src/lib/status.ts` (two new helpers)
- Test: `desktop/src/lib/status.test.ts`

**Interfaces:**
- Consumes: `Status` (with optional `interval_seconds`), `Decision` (from `parse.ts`).
- Produces:
  - `freshness(status: Status | null, nowMs: number) -> { ageSec: number | null; label: string; stale: boolean }`
  - `brainHealth(decisions: Decision[]) -> { state: "ok" | "degraded" | "unknown"; count: number }`

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/lib/status.test.ts`. First ensure the import line at the top of the file includes the new helpers — change the existing `import { … } from "./status";` to also import `freshness` and `brainHealth`. Then append:

```ts
test("freshness: fresh status -> ago label, not stale", () => {
  const now = 1_000_000_000_000;
  const status = { ts: new Date(now - 8_000).toISOString(), interval_seconds: 900 } as any;
  const f = freshness(status, now);
  expect(f.stale).toBe(false);
  expect(f.ageSec).toBe(8);
  expect(f.label).toBe("updated 8s ago");
});

test("freshness: past 2.5x interval -> stale", () => {
  const now = 1_000_000_000_000;
  const status = { ts: new Date(now - 2_300_000).toISOString(), interval_seconds: 900 } as any; // 2300s > 2250s
  expect(freshness(status, now).stale).toBe(true);
});

test("freshness: missing interval -> 900s fallback", () => {
  const now = 1_000_000_000_000;
  const fresh = { ts: new Date(now - 2_000_000).toISOString() } as any;  // 2000s < 2250s -> not stale
  const stale = { ts: new Date(now - 2_300_000).toISOString() } as any;  // 2300s > 2250s -> stale
  expect(freshness(fresh, now).stale).toBe(false);
  expect(freshness(stale, now).stale).toBe(true);
});

test("freshness: no status -> no-data, stale", () => {
  const f = freshness(null, 1_000_000_000_000);
  expect(f.ageSec).toBe(null);
  expect(f.stale).toBe(true);
  expect(f.label).toBe("no data · is the bot running?");
});

test("freshness: minute and hour formatting", () => {
  const now = 1_000_000_000_000;
  expect(freshness({ ts: new Date(now - 240_000).toISOString() } as any, now).label).toBe("updated 4m ago");
  expect(freshness({ ts: new Date(now - 7_200_000).toISOString() } as any, now).label).toBe("updated 2h ago");
});

test("brainHealth: latest reason is llm-fallback -> degraded with trailing count", () => {
  const decisions = [
    { reason: "rsi ok" }, { reason: "llm-fallback: x" }, { reason: "llm-fallback: y" },
  ] as any;
  expect(brainHealth(decisions)).toEqual({ state: "degraded", count: 2 });
});

test("brainHealth: latest reason healthy -> ok", () => {
  expect(brainHealth([{ reason: "llm-fallback: x" }, { reason: "buy signal" }] as any))
    .toEqual({ state: "ok", count: 0 });
});

test("brainHealth: no decisions -> unknown", () => {
  expect(brainHealth([])).toEqual({ state: "unknown", count: 0 });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/status.test.ts`
Expected: FAIL — `freshness`/`brainHealth` are not exported.

- [ ] **Step 3: Implement**

In `desktop/src/lib/parse.ts`, add `interval_seconds?: number` to the `Status` type (alongside the other optional fields `mode?`/`halted?`/`armed?`):

```typescript
export type Status = { ts: string; strategy: string; exchange: string; mode?: string; halted?: boolean; armed?: boolean;
                       interval_seconds?: number; risk: RiskStatus; funding: FundingStatus };
```

In `desktop/src/lib/status.ts`, add the `Decision` type to the existing import from `./parse` (the file already imports `Status`; extend it to `import type { Status, Decision } from "./parse";`). Then append both helpers:

```ts
function fmtAge(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${Math.round(sec / 3600)}h`;
}

export function freshness(status: Status | null, nowMs: number): { ageSec: number | null; label: string; stale: boolean } {
  if (!status?.ts) return { ageSec: null, label: "no data · is the bot running?", stale: true };
  const ageSec = Math.max(0, (nowMs - Date.parse(status.ts)) / 1000);
  const interval = status.interval_seconds ?? 900;
  return { ageSec, label: `updated ${fmtAge(ageSec)} ago`, stale: ageSec > 2.5 * interval };
}

export function brainHealth(decisions: Decision[]): { state: "ok" | "degraded" | "unknown"; count: number } {
  if (!decisions.length) return { state: "unknown", count: 0 };
  if (!decisions[decisions.length - 1].reason.startsWith("llm-fallback:")) return { state: "ok", count: 0 };
  let count = 0;
  for (let i = decisions.length - 1; i >= 0 && decisions[i].reason.startsWith("llm-fallback:"); i--) count++;
  return { state: "degraded", count };
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS — the new helper tests + existing.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/status.ts desktop/src/lib/status.test.ts
git commit -m "feat(dashboard): freshness + brainHealth lib helpers (Status.interval_seconds)"
```

---

### Task 4: Desktop — Sidebar freshness line + brain chip

**Files:**
- Modify: `desktop/src/renderer/src/components/Sidebar.tsx` (freshness line + brain chip + `decisions` prop)
- Modify: `desktop/src/renderer/src/App.tsx` (pass `decisions` to `Sidebar`)
- Modify: `desktop/src/renderer/src/index.css` (`.rail-fresh`, `.brain-chip` styles)

**Interfaces:**
- Consumes: `freshness`, `brainHealth` (Task 3); `Decision` (parse).

- [ ] **Step 1: Update the Sidebar**

In `desktop/src/renderer/src/components/Sidebar.tsx`:

(a) Change the import on line 2-3 to add `Decision` and the two helpers:

```tsx
import type { State, Status, Decision } from "../../../lib/parse";
import { modeBadge, freshness, brainHealth } from "../../../lib/status";
```

(b) Add `decisions` to the props type and destructure (the component signature at lines 23-28):

```tsx
export default function Sidebar({ status, state, view, onNavigate, decisions }: {
  status: Status | null;
  state: State | null;
  view: View;
  onNavigate: (v: View) => void;
  decisions: Decision[];
}) {
```

(c) Just after the `const badge = …` line (line 29), add:

```tsx
  const fresh = freshness(status, Date.now());   // re-evaluated on every 5s poll re-render
  const brain = brainHealth(decisions);
```

(d) Replace the mode-badge block (lines 57-60) with the badge followed by the freshness line and brain chip:

```tsx
      <div className={`mode-badge mode-${badge.tone}`}>
        <span className="mode-dot" />
        {badge.label}
      </div>

      <div className={`rail-fresh${fresh.stale ? " stale" : ""}`}>
        {fresh.stale && fresh.ageSec !== null ? `STALE · ${fresh.label}` : fresh.label}
      </div>

      {brain.state !== "unknown" && (
        <div className={`brain-chip brain-${brain.state}`}>
          {brain.state === "ok" ? "Brain OK" : `Brain DEGRADED${brain.count > 1 ? ` · ${brain.count} cycles` : ""}`}
        </div>
      )}
```

- [ ] **Step 2: Pass `decisions` from App**

In `desktop/src/renderer/src/App.tsx`, find the `<Sidebar … />` usage and add the `decisions` prop. It currently passes `status`/`state`/`view`/`onNavigate`; add:

```tsx
        decisions={snap.decisions}
```

- [ ] **Step 3: CSS**

Append to `desktop/src/renderer/src/index.css`:

```css
.rail-fresh { color: var(--muted); font-size: 11px; margin-top: 6px; }
.rail-fresh.stale { color: var(--down); font-weight: 600; }
.brain-chip { font-size: 11px; margin-top: 6px; padding: 2px 8px; border-radius: 6px; display: inline-block; }
.brain-ok { color: var(--muted); }
.brain-degraded { color: var(--down); background: rgba(239,68,68,0.12); }
```

- [ ] **Step 4: Build + test**

Run: `cd desktop && npm test && npm run build`
Expected: vitest green; build exit 0.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/src/components/Sidebar.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): rail freshness line (STALE) + brain-health chip"
```

---

### Task 5: Desktop — DecisionLog collapses repeated reasons

**Files:**
- Modify: `desktop/src/renderer/src/components/DecisionLog.tsx`
- Modify: `desktop/src/renderer/src/index.css` (`.dup-count` style)

**Interfaces:**
- Consumes: `Decision` (parse) — unchanged prop shape.

- [ ] **Step 1: Rewrite DecisionLog with collapse + truncation**

Replace the entire contents of `desktop/src/renderer/src/components/DecisionLog.tsx` with:

```tsx
import type { Decision } from "../../../lib/parse";

type Row = Decision & { count: number };

// Collapse CONSECUTIVE non-executed rows with an identical reason into one row
// carrying a ×N count. Executed trades always stay their own row.
function collapse(items: Decision[]): Row[] {
  const out: Row[] = [];
  for (const d of items) {
    const prev = out[out.length - 1];
    if (prev && !prev.executed && !d.executed && prev.reason === d.reason) {
      prev.count += 1;
    } else {
      out.push({ ...d, count: 1 });
    }
  }
  return out;
}

function short(reason: string): string {
  return reason.length > 80 ? reason.slice(0, 79) + "…" : reason;
}

export default function DecisionLog({ decisions }: { decisions: Decision[] }) {
  const rows = collapse(decisions.slice(-50)).slice(-30).reverse();
  if (!rows.length) return <div className="empty">No decisions logged yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>Status</th><th>Reason</th></tr>
      </thead>
      <tbody>
        {rows.map((d, i) => (
          <tr key={`${d.ts}-${d.symbol}-${i}`}>
            <td className="muted">{new Date(d.ts).toLocaleTimeString()}</td>
            <td>{d.symbol}</td>
            <td><span className={`badge ${d.action}`}>{d.action}</span></td>
            <td>${d.price.toFixed(2)}</td>
            <td>{d.executed
              ? <span className="exec-yes">✓ done</span>
              : <span className="exec-no">skipped</span>}</td>
            <td className="muted" title={d.reason}>
              {short(d.reason)}{d.count > 1 && <span className="dup-count"> ×{d.count}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: CSS**

Append to `desktop/src/renderer/src/index.css`:

```css
.dup-count { color: var(--accent); font-weight: 600; }
```

- [ ] **Step 3: Build + test**

Run: `cd desktop && npm test && npm run build`
Expected: vitest unchanged-green; build exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/DecisionLog.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): DecisionLog collapses repeated reasons into ×N rows"
```

---

### Task 6: README + final verification

**Files:**
- Modify: `README.md`
- Verify: build + controller Playwright

- [ ] **Step 1: Update the README**

In `README.md`, in the dashboard paragraph, add a sentence about liveness:

```markdown
The sidebar shows data **freshness** ("updated 8s ago") and flips to **STALE · bot stopped?** when the
last `status.json` is older than ~2.5× `interval_seconds` (set this in `config.yaml` to match your cron
cadence). It also shows a **brain-health** chip (OK / DEGRADED) derived from the latest decisions, and the
decision log collapses repeated identical reasons into one `×N` row.
```

- [ ] **Step 2: Full suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest green; build exit 0.

- [ ] **Step 3: Playwright visual verification (CONTROLLER-RUN)**

The controller renders the real `App` (or the built renderer) via a harness stubbing `window.api.getSnapshot` with status `ts`/`interval_seconds` and `decisions`, then verifies at 1280/768/375: a fresh bot shows "updated Xs ago" + Brain OK; an old `status.ts` shows `STALE · bot stopped?`; fallback-reason decisions show Brain DEGRADED + a collapsed `×N` row; a null status shows "no data · is the bot running?". Clean up harness artifacts. (Controller step, not the task subagent.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document dashboard liveness (freshness, STALE, brain health, log collapse)"
```

---

## Self-Review

**Spec coverage:**
- A1 freshness (cadence-aware, STALE) → Task 1 (config) + Task 2 (status) + Task 3 (`freshness`) + Task 4 (Sidebar line) ✓
- A2 brain health (client-derived) → Task 3 (`brainHealth`) + Task 4 (chip) ✓
- A3 decision-log collapse → Task 5 ✓
- backward-compat (optional `interval_seconds`, 900 fallback) → Task 3 `freshness` fallback + Task 1 default ✓
- no safety/toggle/create_order change; no new deps → Global Constraints; tasks touch only display metadata ✓
- README + Playwright → Task 6 ✓

**Placeholder scan:** none — every code step shows full code or exact insertion text.

**Type/signature consistency:**
- `Config.interval_seconds: int` (default 900) — Task 1 defines, Task 2 consumes (`cfg.interval_seconds`) ✓
- `status.json.interval_seconds` — Task 2 writes, Task 3 `Status.interval_seconds?` reads ✓
- `freshness(status?, nowMs) -> {ageSec, label, stale}` — Task 3 defines, Task 4 consumes ✓
- `brainHealth(decisions) -> {state, count}` — Task 3 defines, Task 4 consumes ✓
- `Sidebar` gains a `decisions: Decision[]` prop — Task 4 defines + App passes it ✓
- DecisionLog prop shape unchanged (`decisions: Decision[]`) — Task 5 ✓
