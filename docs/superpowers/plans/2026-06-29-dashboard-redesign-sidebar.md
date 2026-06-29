# Dashboard UX Redesign (Nav Sidebar) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat card-stack dashboard with a fixed nav sidebar (pinned, color-coded mode/halted status + equity/P&L) plus section views, keeping the dark-glass palette and all data/engine code unchanged.

**Architecture:** A `useState<View>` in `App.tsx` drives a left rail (`Sidebar.tsx`) whose nav links swap the main view (no router). The rail pins the safety-critical status via a unit-tested `modeBadge` helper. Existing panel components are reused as-is; `StatusStrip` is retired into the rail status + an Overview Risk card.

**Tech Stack:** Electron + React + TypeScript, electron-vite build, vitest (node env, `src/lib/**` only). Charts via the existing recharts components.

## Global Constraints

- **Pure presentation. NO engine/Python changes.** `data/status.json` already carries `mode`, `halted`, `risk`, `funding`; the snapshot files are unchanged.
- **Keep the palette/fonts/glass-card aesthetic** and every panel component's internals (`EquityChart`, `PositionsTable`, `TradesTable`, `SentimentPanel`, `BacktestChart`). Only structure/hierarchy/status treatment change.
- **vitest covers `src/lib/**` only (node env, no jsdom).** Only the `modeBadge` helper gets a unit test (TDD red→green). Components are verified by `npm run build` (type-check + bundle) and controller-run Playwright — do NOT add component unit tests.
- **`modeBadge` tone:** `halted` true ⇒ tone `"halted"` for EVERY mode; else `live`→live, `shadow`→shadow, anything else→paper.
- **No new dependencies.**
- **Commit trailers** (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Desktop commands (run from `desktop/`): `npm test` (vitest), `npm run build`.
- Full design: `docs/superpowers/specs/2026-06-29-dashboard-redesign-sidebar-design.md`.

---

### Task 1: `modeBadge` helper (lib, TDD)

**Files:**
- Modify: `desktop/src/lib/status.ts` (add `ModeTone` + `modeBadge`)
- Test: `desktop/src/lib/status.test.ts`

**Interfaces:**
- Produces: `modeBadge(mode?: string, halted?: boolean) -> { label: string; tone: ModeTone }` where `ModeTone = "live" | "shadow" | "paper" | "halted"`.

- [ ] **Step 1: Write the failing test**

Append to `desktop/src/lib/status.test.ts`. Add `modeBadge` to the existing import on line 2 (`import { leverageMode, shortingLabel, fundingSummary, accruedLabel, modeBadge } from "./status";`), then add:

```ts
test("modeBadge maps mode to tone+label", () => {
  expect(modeBadge("paper", false)).toEqual({ label: "PAPER", tone: "paper" });
  expect(modeBadge("shadow", false)).toEqual({ label: "SHADOW", tone: "shadow" });
  expect(modeBadge("live", false)).toEqual({ label: "LIVE", tone: "live" });
  expect(modeBadge(undefined, false)).toEqual({ label: "PAPER", tone: "paper" });
});

test("modeBadge: halted overrides every mode", () => {
  expect(modeBadge("live", true)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge("paper", true)).toEqual({ label: "HALTED", tone: "halted" });
  expect(modeBadge("shadow", true)).toEqual({ label: "HALTED", tone: "halted" });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/status.test.ts`
Expected: FAIL — `modeBadge` is not exported.

- [ ] **Step 3: Implement**

Append to `desktop/src/lib/status.ts`:

```ts
export type ModeTone = "live" | "shadow" | "paper" | "halted";

export function modeBadge(mode?: string, halted?: boolean): { label: string; tone: ModeTone } {
  if (halted) return { label: "HALTED", tone: "halted" };
  if (mode === "live") return { label: "LIVE", tone: "live" };
  if (mode === "shadow") return { label: "SHADOW", tone: "shadow" };
  return { label: "PAPER", tone: "paper" };
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd desktop && npm test`
Expected: PASS (new + existing; was 20, now 22).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/status.ts desktop/src/lib/status.test.ts
git commit -m "feat(dashboard): modeBadge helper (mode/halted -> tone+label)"
```

---

### Task 2: `Sidebar.tsx` + rail / mode-color CSS

**Files:**
- Create: `desktop/src/renderer/src/components/Sidebar.tsx`
- Modify: `desktop/src/renderer/src/index.css` (append rail + mode-color rules + responsive)

**Interfaces:**
- Consumes: `modeBadge` (Task 1); `Status`, `State` from `../../../lib/parse`.
- Produces: `export type View = "overview" | "positions" | "activity" | "sentiment" | "backtest";` and `default Sidebar({ status, state, view, onNavigate })` where `onNavigate: (v: View) => void`. (App imports `View` from here in Task 3.)

- [ ] **Step 1: Create the Sidebar component**

Create `desktop/src/renderer/src/components/Sidebar.tsx`:

```tsx
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

export default function Sidebar({ status, state, view, onNavigate }: {
  status: Status | null;
  state: State | null;
  view: View;
  onNavigate: (v: View) => void;
}) {
  const badge = modeBadge(status?.mode, status?.halted);
  const cash = state?.cash ?? 0;
  const eq = state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : equity;
  const pnl = equity - start;

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

      <div className="rail-foot">
        {status ? `${status.exchange} · ${status.strategy}` : "—"}
        <br />
        read-only · polls 5s
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Append the CSS**

Append to `desktop/src/renderer/src/index.css`:

```css
/* --- redesign: rail + mode colors --- */
:root {
  --mode-paper: #93a0bd; --mode-shadow: #60a5fa; --mode-live: #f59e0b; --mode-halted: #f87171;
}
.app { display: flex; min-height: 100vh; }
.sidebar { width: 240px; flex: 0 0 240px; height: 100vh; position: sticky; top: 0;
  display: flex; flex-direction: column; gap: 16px; padding: 22px 18px;
  border-right: 1px solid var(--glass-border); background: rgba(255,255,255,0.025); }
.brand { font-size: 17px; font-weight: 700; }
.mode-badge { display: inline-flex; align-items: center; gap: 8px; align-self: flex-start;
  padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 700; letter-spacing: 0.5px;
  color: var(--mode-paper); border: 1px solid currentColor; }
.mode-dot { width: 8px; height: 8px; border-radius: 999px; background: currentColor; }
.mode-paper { color: var(--mode-paper); }
.mode-shadow { color: var(--mode-shadow); }
.mode-live { color: var(--mode-live); }
.mode-halted { color: var(--mode-halted); background: rgba(248,113,113,0.12); }
.rail-eq { font-size: 24px; font-weight: 700; }
.rail-pnl { font-size: 14px; font-weight: 600; margin-top: 2px; }
.rail-nav { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.rail-link { text-align: left; background: none; border: none; color: var(--muted);
  font: inherit; font-size: 14px; padding: 8px 12px; border-radius: 8px; cursor: pointer; }
.rail-link:hover { background: var(--glass); color: var(--text); }
.rail-link.active { background: var(--glass); color: var(--text); font-weight: 600;
  box-shadow: inset 2px 0 0 var(--accent); }
.rail-foot { margin-top: auto; color: var(--muted); font-size: 12px; line-height: 1.6; }
@media (max-width: 820px) {
  .app { flex-direction: column; }
  .sidebar { width: auto; flex: none; height: auto; position: static;
    flex-direction: row; flex-wrap: wrap; align-items: center; gap: 10px 14px;
    border-right: none; border-bottom: 1px solid var(--glass-border); }
  .rail-acct { margin-left: auto; text-align: right; }
  .rail-nav { flex-direction: row; flex-wrap: wrap; margin-top: 0; width: 100%; }
  .rail-foot { margin-top: 0; width: 100%; }
}
```

- [ ] **Step 3: Build to verify it type-checks**

Run: `cd desktop && npm run build`
Expected: exit 0 (tsc type-checks `Sidebar.tsx` even though nothing imports it yet; CSS is valid). vitest unaffected.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/Sidebar.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): Sidebar rail (pinned status + equity/P&L + nav) + mode-color CSS"
```

---

### Task 3: `App.tsx` restructure — sidebar + views, retire `StatusStrip`

**Files:**
- Modify: `desktop/src/renderer/src/App.tsx` (full rewrite)
- Delete: `desktop/src/renderer/src/components/StatusStrip.tsx`
- Modify: `desktop/src/renderer/src/index.css` (add `.main`; remove dead `.wrap`/`.title`/`.sub`)

**Interfaces:**
- Consumes: `Sidebar`, `View` (Task 2); `leverageMode`, `shortingLabel`, `fundingSummary` from `../../lib/status`; existing panel components.
- Produces: the restructured app (rail + view area). No exports other than default `App`.

- [ ] **Step 1: Rewrite `App.tsx`**

Replace the entire contents of `desktop/src/renderer/src/App.tsx` with:

```tsx
import { useEffect, useState } from "react";
import type { Snapshot, Status } from "../../lib/parse";
import { leverageMode, shortingLabel, fundingSummary } from "../../lib/status";
import EquityChart from "./components/EquityChart";
import PositionsTable from "./components/PositionsTable";
import DecisionLog from "./components/DecisionLog";
import TradesTable from "./components/TradesTable";
import SentimentPanel from "./components/SentimentPanel";
import BacktestChart from "./components/BacktestChart";
import Sidebar, { type View } from "./components/Sidebar";

const EMPTY: Snapshot = { state: null, trades: [], decisions: [], sentiment: null, status: null, backtest: [] };
const api = (window as unknown as { api: { getSnapshot: () => Promise<Snapshot> } }).api;

export default function App(): React.JSX.Element {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [view, setView] = useState<View>("overview");

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

  return (
    <div className="app">
      <Sidebar status={snap.status} state={snap.state} view={view} onNavigate={setView} />
      <main className="main">
        {view === "overview" && <Overview snap={snap} />}
        {view === "positions" && (
          <section className="card"><h2>Open positions</h2><PositionsTable state={snap.state} /></section>
        )}
        {view === "activity" && <Activity snap={snap} />}
        {view === "sentiment" && (
          <section className="card"><h2>Sentiment</h2><SentimentPanel sentiment={snap.sentiment} /></section>
        )}
        {view === "backtest" && (
          <section className="card"><h2>Backtest</h2><BacktestChart points={snap.backtest} /></section>
        )}
      </main>
    </div>
  );
}

function Overview({ snap }: { snap: Snapshot }): React.JSX.Element {
  const cash = snap.state?.cash ?? 0;
  const eq = snap.state?.equity_history;
  const equity = eq && eq.length ? eq[eq.length - 1].equity : cash;
  const start = eq && eq.length ? eq[0].equity : equity;
  const pnl = equity - start;
  return (
    <div className="grid">
      <section className="card">
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
      </section>
      <section className="card"><h2>Equity curve</h2><EquityChart history={eq ?? []} /></section>
      <section className="card"><h2>Open positions</h2><PositionsTable state={snap.state} /></section>
      <section className="card"><h2>Risk</h2><RiskCard status={snap.status} /></section>
    </div>
  );
}

function RiskCard({ status }: { status: Status | null }): React.JSX.Element {
  if (!status) return <div className="empty">No status yet.</div>;
  const r = status.risk;
  const chips: [string, string][] = [
    ["Leverage", leverageMode(r.leverage)],
    ["Shorting", shortingLabel(r.allow_short)],
    ["Funding", fundingSummary(status)],
    ["Max position", `${(r.max_position_pct * 100).toFixed(0)}%`],
    ["Stop", `${(r.stop_loss_pct * 100).toFixed(0)}%`],
    ["Maint. margin", `${(r.maintenance_margin_pct * 100).toFixed(2)}%`],
  ];
  return (
    <div className="chips">
      {chips.map(([k, v]) => (
        <div className="chip" key={k}><span className="chip-k">{k}</span><span className="chip-v">{v}</span></div>
      ))}
    </div>
  );
}

function Activity({ snap }: { snap: Snapshot }): React.JSX.Element {
  return (
    <div className="grid">
      <section className="card"><h2>Decisions</h2><DecisionLog decisions={snap.decisions} /></section>
      <section className="card"><h2>Trades</h2><TradesTable trades={snap.trades} /></section>
    </div>
  );
}
```

- [ ] **Step 2: Delete the retired component**

```bash
git rm desktop/src/renderer/src/components/StatusStrip.tsx
```

(Verify nothing else imports it: `grep -rn "StatusStrip" desktop/src` should return no matches after the App rewrite.)

- [ ] **Step 3: Update CSS — add `.main`, remove dead rules**

In `desktop/src/renderer/src/index.css`: add the `.main` rule, and remove the now-unused `.wrap`, `.title`, `.sub` rules (App no longer renders them).

Add:
```css
.main { flex: 1; min-width: 0; padding: 28px 32px 56px; }
.main > .grid { margin: 0; }
```

Remove these three lines (they are dead after the rewrite):
```css
.wrap { max-width: 1100px; margin: 0 auto; padding: 28px 22px 56px; }
.title { font-size: 22px; font-weight: 700; }
.sub { color: var(--muted); font-size: 13px; margin-top: 2px; }
```

(Keep everything else — `.grid`, `.card`, `.kpis`, `.kpi`, `.chips`, `.chip*`, tables, badges, `.sent-*`, etc. — all still used.)

- [ ] **Step 4: Build + test**

Run: `cd desktop && npm test && npm run build`
Expected: vitest PASS (22); build exit 0; `grep -rn "StatusStrip" desktop/src` → no matches.

- [ ] **Step 5: Commit**

```bash
git add -A desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): nav-sidebar app shell + section views; retire StatusStrip"
```

---

### Task 4: DecisionLog — explicit Executed / skipped cue

**Files:**
- Modify: `desktop/src/renderer/src/components/DecisionLog.tsx`
- Modify: `desktop/src/renderer/src/index.css` (two helper classes)

**Interfaces:**
- Consumes: `Decision` (unchanged). No new exports.

- [ ] **Step 1: Replace the cryptic `*` with a Status column**

Replace the entire contents of `desktop/src/renderer/src/components/DecisionLog.tsx` with:

```tsx
import type { Decision } from "../../../lib/parse";

export default function DecisionLog({ decisions }: { decisions: Decision[] }) {
  const recent = decisions.slice(-30).reverse();
  if (!recent.length) return <div className="empty">No decisions logged yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Action</th><th>Price</th><th>Status</th><th>Reason</th></tr>
      </thead>
      <tbody>
        {recent.map((d) => (
          <tr key={`${d.ts}-${d.symbol}`}>
            <td className="muted">{new Date(d.ts).toLocaleTimeString()}</td>
            <td>{d.symbol}</td>
            <td><span className={`badge ${d.action}`}>{d.action}</span></td>
            <td>${d.price.toFixed(2)}</td>
            <td>{d.executed
              ? <span className="exec-yes">✓ done</span>
              : <span className="exec-no">skipped</span>}</td>
            <td className="muted">{d.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Add the two helper classes**

Append to `desktop/src/renderer/src/index.css`:

```css
.exec-yes { color: var(--up); font-weight: 600; }
.exec-no { color: var(--muted); }
```

- [ ] **Step 3: Build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/DecisionLog.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): explicit Executed/skipped cue in DecisionLog"
```

---

### Task 5: README + final verification

**Files:**
- Modify: `README.md` (dashboard description)
- Verify: build + Playwright (Playwright is controller-run)

- [ ] **Step 1: Update the README dashboard description**

In `README.md`, find the paragraph in the Sentiment section that begins "The desktop dashboard shows a **Sentiment** panel" and describes the "**Status** strip ... **Trades** table ... **Backtest** chart". Replace that descriptive sentence about the layout with:

```markdown
The desktop dashboard is organized as a **nav sidebar + section views**. The sidebar pins the
bot's **mode** (color-coded — PAPER / SHADOW / LIVE, and a red **HALTED** when `data/HALT` is
present) plus live equity and P&L, so the safety-critical state is always visible. The nav switches
between **Overview** (account, equity curve, open positions, risk limits), **Positions**,
**Activity** (decisions + trades), **Sentiment**, and **Backtest** (strategy vs buy-and-hold from
`data/backtest_equity.csv`). It reads the same `data/*.json` snapshots the bot writes each cycle.
```

(Adjust the surrounding wording minimally so the paragraph still reads well; keep the Sentiment-panel details and the sources table that follow.)

- [ ] **Step 2: Full suites**

Run: `cd desktop && npm test && npm run build`
Expected: vitest 22 PASS; build exit 0.

- [ ] **Step 3: Playwright visual verification (CONTROLLER-RUN)**

The controller builds a harness that stubs `window.api.getSnapshot` (setting `window.api` BEFORE dynamically importing `App`) and renders the real `App`, then screenshots at 1280 / 768 / 375 across **paper / live / halted** statuses and the **Overview**, **Activity**, and one other view. Confirm: rail status color per mode, the red HALTED treatment, pinned equity/P&L, nav switches the view, and the rail collapses to a top bar at 375. Clean up harness artifacts after. (This step is performed by the controller during the final review phase, not the task subagent.)

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: dashboard README describes the nav-sidebar layout"
```

---

## Self-Review

**Spec coverage:**
- Nav sidebar + view state (no router), default Overview → Task 2 (Sidebar/View) + Task 3 (App) ✓
- Pinned color-coded status (mode/halted) via `modeBadge` → Task 1 (helper) + Task 2 (rail) ✓
- Pinned equity + P&L → Task 2 ✓
- Color semantics (paper/shadow/live/halted vars + halted override) → Task 1 (tone) + Task 2 (CSS vars/classes) ✓
- Views: Overview (account+equity+positions+risk), Positions, Activity, Sentiment, Backtest → Task 3 ✓
- Honest title (drop "Paper-Trading") → Task 2 (brand) + Task 3 (no `.title`/`.sub`) ✓
- Risk params demoted to Overview Risk card → Task 3 (`RiskCard`) ✓
- Retire `StatusStrip` → Task 3 (delete + grep) ✓
- DecisionLog Executed/skipped cue → Task 4 ✓
- Responsive rail→top bar at ≤820 → Task 2 CSS ✓
- Engine unchanged, palette kept, no new deps → Global Constraints; no task touches engine/ or package.json ✓
- Testing: modeBadge unit test + build + Playwright → Tasks 1, 3, 5 ✓

**Placeholder scan:** none — every code step shows full file content or exact append/remove text. The README step names the exact paragraph to edit and gives the replacement verbatim.

**Type/signature consistency:**
- `modeBadge(mode?, halted?) -> {label, tone}` / `ModeTone` — Task 1 defines, Task 2 consumes ✓
- `View` + `Sidebar({status,state,view,onNavigate})` — Task 2 defines+exports, Task 3 imports `Sidebar, { type View }` ✓
- Panel props reused exactly as today: `EquityChart history`, `PositionsTable state`, `DecisionLog decisions`, `TradesTable trades`, `SentimentPanel sentiment`, `BacktestChart points` — Task 3 ✓
- `leverageMode`/`shortingLabel`/`fundingSummary` reused from `lib/status` in `RiskCard` — Task 3 ✓
- CSS vars referenced exist or are added: `--up`/`--down`/`--muted`/`--text`/`--glass`/`--glass-border`/`--accent` (existing), `--mode-*` (added Task 2) ✓
```
