# Dashboard Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop dashboard surface the full paper-trading feature set — the bot's resolved mode/config, funding (rate + cumulative), a trades table, and a backtest results chart.

**Architecture:** Two small engine writes (a `funding_accrued` accumulator persisted in `state.json`, and a resolved `status.json` written each cycle) plus four read-only dashboard surfaces that consume snapshot files in `data/` through the existing resilient `readOr` reader.

**Tech Stack:** Python 3.14 engine (pytest). Electron/TypeScript/React/recharts dashboard; vitest is **node-env, `src/lib/**` only** — pure helpers get unit tests, components are verified by `npm run build` + Playwright.

## Global Constraints

- **TDD always:** red → green per step. Run the named command and confirm the stated result before moving on.
- **Read-only display + two engine writes only.** No change to the gate, fills, funding mechanics, or liquidation. `engine/broker.py`, `models.py`, `indicators.py`, `strategies.py`, `sentiment.py`, `market.py`, `llm.py`, `backtest.py`, `config.py` are NOT modified.
- **`status.json` is advisory** — written wrapped in try/except so a write error never aborts the trading cycle (same pattern as the existing sentiment write). It carries the **resolved** config (`allow_short` after auto-resolution, leverage after the load-time clamp).
- **`funding_accrued`** is signed: negative = net paid, positive = net received. It changes ONLY when funding actually charges (gated by the existing `funding_due and pos.qty != 0`). Funding off ⇒ stays `0.0`.
- **Backward-compatible state:** an old `state.json` without `funding_accrued` loads as `0.0`.
- **No new dependencies** (recharts already present). Desktop vitest stays `src/lib/**`-only (node env); do NOT add jsdom or component tests.
- **Commit trailers** (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q`. Desktop: `cd desktop && npm test` and `npm run build`.
- The full design is `docs/superpowers/specs/2026-06-28-dashboard-completeness-design.md`.

---

### Task 1: Cumulative funding accumulator (`State.funding_accrued`)

**Files:**
- Modify: `engine/state.py` (`State` dataclass, `load_state`, `save_state_atomic`)
- Modify: `engine/bot.py` (accumulate on funding)
- Test: `tests/test_state.py`, `tests/test_bot.py`

**Interfaces:**
- Produces: `State(..., last_funding_ts=None, funding_accrued: float = 0.0)`, persisted; the bot does `st.funding_accrued += pay` where funding is charged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
def test_funding_accrued_roundtrips(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.funding_accrued = -1.25
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.funding_accrued == -1.25

def test_funding_accrued_defaults_zero_and_old_snapshot(tmp_path):
    import json
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.funding_accrued == 0.0
    save_state_atomic(st, str(tmp_path))
    raw = json.loads((tmp_path / "state.json").read_text())
    del raw["funding_accrued"]
    (tmp_path / "state.json").write_text(json.dumps(raw))
    assert load_state(str(tmp_path), 10000.0, ["BTC/USDT"]).funding_accrued == 0.0
```

Append to `tests/test_bot.py`:

```python
def test_funding_accrues_cumulative(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.funding_rate = 0.001
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=150.0, stop_price=1.0)
    st.last_funding_ts = "2020-01-01T00:00:00+00:00"
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.funding_accrued == pytest.approx(-0.001 * 1.0 * 159.0)   # long paid -> negative

def test_funding_accrued_stays_zero_when_off(tmp_path):
    cfg = _cfg(tmp_path)   # funding off (rate defaults 0.0)
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=150.0, stop_price=1.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.funding_accrued == 0.0
```

(`tests/test_bot.py` already imports `pytest`.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_state.py tests/test_bot.py -k "funding_accru" -q`
Expected: FAIL — `State` has no `funding_accrued`.

- [ ] **Step 3: Implement**

In `engine/state.py`, extend `State`:

```python
@dataclass
class State:
    cash: float
    positions: dict
    equity_history: list = field(default_factory=list)
    last_funding_ts: str | None = None
    funding_accrued: float = 0.0
```

In `load_state`, the file-branch `return State(...)` — add the kwarg:

```python
    return State(cash=raw["cash"], positions=positions,
                 equity_history=raw.get("equity_history", []),
                 last_funding_ts=raw.get("last_funding_ts"),
                 funding_accrued=raw.get("funding_accrued", 0.0))
```

In `save_state_atomic`, add to the `payload` dict (after `"last_funding_ts": ...`):

```python
        "funding_accrued": state.funding_accrued,
```

In `engine/bot.py`, in the funding-charge block, add the accumulate line (the block currently reads `pay = ...`, `st.cash = max(...)`, `print(...)`):

```python
            if funding_due and pos.qty != 0:
                pay = broker.funding_payment(pos, price, cfg.risk.funding_rate)
                st.cash = max(0.0, st.cash + pay)
                st.funding_accrued += pay
                print(f"[{sym}] FUNDING {pay:+.4f}")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_state.py tests/test_bot.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/state.py engine/bot.py tests/test_state.py tests/test_bot.py
git commit -m "feat: track cumulative funding_accrued in state"
```

---

### Task 2: Resolved status snapshot (`state.write_status` + bot write)

**Files:**
- Modify: `engine/state.py` (`+ write_status`)
- Modify: `engine/bot.py` (build + write `status.json` each cycle)
- Test: `tests/test_state.py`, `tests/test_bot.py`

**Interfaces:**
- Consumes: `State.funding_accrued` (Task 1).
- Produces: `state.write_status(snapshot: dict, data_dir: str)` → atomic `data/status.json`. The bot writes `{ts, strategy, exchange, risk:{allow_short, leverage, maintenance_margin_pct, funding_rate, funding_interval_hours, max_position_pct, stop_loss_pct}, funding:{accrued, last_funding_ts}}` each cycle.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
def test_write_status_atomic_json(tmp_path):
    from engine.state import write_status
    import json
    write_status({"ts": "t1", "strategy": "hybrid", "exchange": "binance",
                  "risk": {"allow_short": True, "leverage": 5.0},
                  "funding": {"accrued": -1.0, "last_funding_ts": None}}, str(tmp_path))
    path = tmp_path / "status.json"
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["strategy"] == "hybrid" and loaded["risk"]["allow_short"] is True
    assert not (tmp_path / "status.json.tmp").exists()   # temp cleaned (atomic replace)
```

Append to `tests/test_bot.py`:

```python
def test_status_written_with_resolved_mode(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.risk.allow_short = None        # auto -> resolved from the exchange
    cfg.risk.leverage = 3.0
    monkeypatch.setattr(bot.market_mod, "supports_short", lambda ex: True)
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["strategy"] == cfg.strategy
    assert data["exchange"] == cfg.exchange
    assert data["risk"]["allow_short"] is True      # resolved None -> True (written as a bool)
    assert data["risk"]["leverage"] == 3.0
    assert "accrued" in data["funding"] and "last_funding_ts" in data["funding"]

def test_status_write_failure_does_not_abort(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    def boom(*a, **k):
        raise IOError("disk full")
    monkeypatch.setattr(bot.state_mod, "write_status", boom)
    # the cycle still completes and persists the trade despite the status write failing
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_state.py tests/test_bot.py -k "status" -q`
Expected: FAIL — `write_status` not defined / `status.json` not written.

- [ ] **Step 3: Implement**

In `engine/state.py`, add after `write_sentiment`:

```python
def write_status(snapshot: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "status.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, path)                   # atomic on POSIX
```

In `engine/bot.py`, at the END of `run_once` (after the whole `if prices: … else: …` block, still inside the `with state_mod.acquire_lock(...)` block), add:

```python
        try:                                     # advisory: a status write error never aborts the cycle
            state_mod.write_status({
                "ts": ts,
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
                "funding": {"accrued": st.funding_accrued, "last_funding_ts": st.last_funding_ts},
            }, cfg.data_dir)
        except Exception as e:
            log.warning("status snapshot write failed: %s", e)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_state.py tests/test_bot.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/state.py engine/bot.py tests/test_state.py tests/test_bot.py
git commit -m "feat: write resolved status.json snapshot each cycle"
```

---

### Task 3: Dashboard plumbing — types, parse, reader, formatters

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`Status`/`BacktestPoint` types, `parseBacktestCsv`, widen `Snapshot`)
- Create: `desktop/src/lib/status.ts` (pure formatters)
- Modify: `desktop/src/lib/snapshot.ts` (read `status.json` + `backtest_equity.csv`)
- Modify: `desktop/src/renderer/src/App.tsx` (update `EMPTY` only)
- Test: `desktop/src/lib/parse.test.ts`, `desktop/src/lib/status.test.ts` (new), `desktop/src/lib/snapshot.test.ts`

**Interfaces:**
- Consumes: `status.json` (Task 2) and the backtest CLI's `data/backtest_equity.csv` (header `ts,equity,buy_hold`, a baseline row with an empty `ts`, then data rows).
- Produces: `Status` type; `BacktestPoint = {ts, equity, buyHold}`; `parseBacktestCsv(text) -> BacktestPoint[]`; `Snapshot` widened with `status: Status | null` and `backtest: BacktestPoint[]`; formatters `leverageMode`, `shortingLabel`, `fundingSummary`, `accruedLabel`.

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/lib/parse.test.ts`:

```typescript
import { parseBacktestCsv } from "./parse";

test("parseBacktestCsv parses baseline + data rows", () => {
  const csv = "ts,equity,buy_hold\n,10000,10000\n1700000000000,10250,10100\n";
  const pts = parseBacktestCsv(csv);
  expect(pts).toHaveLength(2);
  expect(pts[0]).toEqual({ ts: "", equity: 10000, buyHold: 10000 });   // baseline (empty ts)
  expect(pts[1]).toEqual({ ts: "1700000000000", equity: 10250, buyHold: 10100 });
});

test("parseBacktestCsv empty / header-only -> []", () => {
  expect(parseBacktestCsv("")).toEqual([]);
  expect(parseBacktestCsv("ts,equity,buy_hold\n")).toEqual([]);
});
```

Create `desktop/src/lib/status.test.ts`:

```typescript
import { test, expect } from "vitest";
import { leverageMode, shortingLabel, fundingSummary, accruedLabel } from "./status";
import type { Status } from "./parse";

const mk = (over: Partial<Status["risk"]>): Status => ({
  ts: "t", strategy: "hybrid", exchange: "binance",
  risk: { allow_short: false, leverage: 1, maintenance_margin_pct: 0.005,
          funding_rate: 0, funding_interval_hours: 8, max_position_pct: 0.25, stop_loss_pct: 0.05, ...over },
  funding: { accrued: 0, last_funding_ts: null },
});

test("leverageMode", () => {
  expect(leverageMode(1)).toBe("1× (off)");
  expect(leverageMode(5)).toBe("5×");
  expect(leverageMode(undefined)).toBe("1× (off)");
});

test("shortingLabel", () => {
  expect(shortingLabel(true)).toBe("on");
  expect(shortingLabel(false)).toBe("off");
});

test("fundingSummary", () => {
  expect(fundingSummary(null)).toBe("off");
  expect(fundingSummary(mk({ funding_rate: 0 }))).toBe("off");
  expect(fundingSummary(mk({ funding_rate: 0.0001, funding_interval_hours: 8 }))).toBe("0.010%/8h");
});

test("accruedLabel", () => {
  expect(accruedLabel(0)).toBe("$0.00");
  expect(accruedLabel(0.8)).toBe("+$0.80 received");
  expect(accruedLabel(-1.234)).toBe("−$1.23 paid");
});
```

Append to `desktop/src/lib/snapshot.test.ts`:

```typescript
test("readSnapshot reads status.json + backtest_equity.csv, defaults when absent", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-status-"));
  writeFileSync(join(dir, "status.json"), JSON.stringify({
    ts: "t1", strategy: "hybrid", exchange: "binance",
    risk: { allow_short: true, leverage: 5, maintenance_margin_pct: 0.005,
            funding_rate: 0.0001, funding_interval_hours: 8, max_position_pct: 0.25, stop_loss_pct: 0.05 },
    funding: { accrued: -1.5, last_funding_ts: "t0" },
  }));
  writeFileSync(join(dir, "backtest_equity.csv"), "ts,equity,buy_hold\n,10000,10000\n1,10200,10100\n");
  const snap = await readSnapshot(dir);
  expect(snap.status?.risk.leverage).toBe(5);
  expect(snap.status?.funding.accrued).toBe(-1.5);
  expect(snap.backtest).toHaveLength(2);
  rmSync(dir, { recursive: true, force: true });

  const empty = mkdtempSync(join(tmpdir(), "snap-nostatus-"));
  const s = await readSnapshot(empty);
  expect(s.status).toBeNull();      // missing -> null
  expect(s.backtest).toEqual([]);   // missing -> []
  rmSync(empty, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/parse.test.ts src/lib/status.test.ts src/lib/snapshot.test.ts`
Expected: FAIL — `parseBacktestCsv`/`status.ts` exports / `status`+`backtest` fields not present.

- [ ] **Step 3: Implement**

In `desktop/src/lib/parse.ts`, add the types (after the `SentimentSnapshot` type) and widen `Snapshot`:

```typescript
export type RiskStatus = { allow_short: boolean; leverage: number; maintenance_margin_pct: number;
                           funding_rate: number; funding_interval_hours: number;
                           max_position_pct: number; stop_loss_pct: number };
export type FundingStatus = { accrued: number; last_funding_ts: string | null };
export type Status = { ts: string; strategy: string; exchange: string;
                       risk: RiskStatus; funding: FundingStatus };
export type BacktestPoint = { ts: string; equity: number; buyHold: number };
```

Replace the `Snapshot` type with:

```typescript
export type Snapshot = { state: State | null; trades: Trade[]; decisions: Decision[];
                         sentiment: SentimentSnapshot | null;
                         status: Status | null; backtest: BacktestPoint[] };
```

Add `parseBacktestCsv` (after `parseSentiment`):

```typescript
export function parseBacktestCsv(text: string): BacktestPoint[] {
  const lines = text.trim().split("\n").filter((l) => l.trim() !== "");
  if (lines.length <= 1) return []; // empty or header-only
  return lines.slice(1).map((line) => {
    const [ts, equity, buyHold] = line.split(",");
    return { ts, equity: Number(equity), buyHold: Number(buyHold) };
  });
}
```

Create `desktop/src/lib/status.ts`:

```typescript
import type { Status } from "./parse";

export function leverageMode(lev?: number): string {
  return lev && lev > 1 ? `${lev}×` : "1× (off)";
}

export function shortingLabel(allow?: boolean): string {
  return allow ? "on" : "off";
}

export function fundingSummary(status: Status | null): string {
  const r = status?.risk;
  if (!r || r.funding_rate === 0) return "off";
  return `${(r.funding_rate * 100).toFixed(3)}%/${r.funding_interval_hours}h`;
}

export function accruedLabel(accrued?: number): string {
  const a = accrued ?? 0;
  if (a > 0) return `+$${a.toFixed(2)} received`;
  if (a < 0) return `−$${Math.abs(a).toFixed(2)} paid`;
  return "$0.00";
}
```

In `desktop/src/lib/snapshot.ts`, extend the import and `readSnapshot`:

```typescript
import { parseTradesCsv, parseDecisions, parseSentiment, parseBacktestCsv, Snapshot, State, SentimentSnapshot, Status, BacktestPoint } from "./parse";
```

```typescript
  const sentiment = await readOr<SentimentSnapshot | null>(join(dir, "sentiment.json"), null, parseSentiment);
  const status = await readOr<Status | null>(join(dir, "status.json"), null, (s) => JSON.parse(s) as Status);
  const backtest = await readOr<BacktestPoint[]>(join(dir, "backtest_equity.csv"), [], parseBacktestCsv);
  return { state, trades, decisions, sentiment, status, backtest };
```

In `desktop/src/renderer/src/App.tsx`, update the `EMPTY` constant:

```typescript
const EMPTY: Snapshot = { state: null, trades: [], decisions: [], sentiment: null, status: null, backtest: [] };
```

- [ ] **Step 4: Run tests + build**

Run: `cd desktop && npm test && npm run build`
Expected: vitest PASS (incl. new); build exits 0 (the `Snapshot` widening + `EMPTY` update keep App.tsx compiling).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/status.ts desktop/src/lib/status.test.ts desktop/src/lib/snapshot.ts desktop/src/lib/parse.test.ts desktop/src/lib/snapshot.test.ts desktop/src/renderer/src/App.tsx
git commit -m "feat: dashboard plumbing for status + backtest (types, parse, reader, formatters)"
```

---

### Task 4: Status strip component

**Files:**
- Create: `desktop/src/renderer/src/components/StatusStrip.tsx`
- Modify: `desktop/src/renderer/src/App.tsx` (render the strip)
- Modify: `desktop/src/renderer/src/index.css` (chip styles)

**Interfaces:**
- Consumes: `snapshot.status` (Task 3); formatters from `lib/status` (Task 3).

- [ ] **Step 1: Create the component**

Create `desktop/src/renderer/src/components/StatusStrip.tsx`:

```tsx
import type { Status } from "../../../lib/parse";
import { leverageMode, shortingLabel, fundingSummary, accruedLabel } from "../../../lib/status";

export default function StatusStrip({ status }: { status: Status | null }) {
  if (!status) return <div className="empty">Waiting for the bot to write status…</div>;
  const r = status.risk;
  const chips: [string, string][] = [
    ["Strategy", status.strategy],
    ["Exchange", status.exchange],
    ["Leverage", leverageMode(r.leverage)],
    ["Shorting", shortingLabel(r.allow_short)],
    ["Funding", fundingSummary(status)],
    ["Accrued", accruedLabel(status.funding.accrued)],
    ["Max position", `${(r.max_position_pct * 100).toFixed(0)}%`],
    ["Stop", `${(r.stop_loss_pct * 100).toFixed(0)}%`],
  ];
  return (
    <div className="chips">
      {chips.map(([k, v]) => (
        <div className="chip" key={k}>
          <span className="chip-k">{k}</span><span className="chip-v">{v}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Wire into App + add CSS**

In `desktop/src/renderer/src/App.tsx`, import the component (with the other component imports):

```typescript
import StatusStrip from "./components/StatusStrip";
```

And add a Status card as the FIRST child of `<div className="grid">` (before the Account card):

```tsx
        <div className="card span2">
          <h2>Status</h2>
          <StatusStrip status={snap.status} />
        </div>
```

Append to `desktop/src/renderer/src/index.css`:

```css
.chips { display: flex; flex-wrap: wrap; gap: 10px; }
.chip { display: flex; flex-direction: column; gap: 2px; padding: 8px 12px;
        background: var(--glass); border: 1px solid var(--glass-border); border-radius: 10px; }
.chip-k { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
.chip-v { font-size: 14px; font-weight: 600; }
```

- [ ] **Step 3: Build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/StatusStrip.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css
git commit -m "feat: dashboard status strip (mode + funding chips)"
```

---

### Task 5: Trades table component

**Files:**
- Create: `desktop/src/renderer/src/components/TradesTable.tsx`
- Modify: `desktop/src/renderer/src/App.tsx` (Trades card)

**Interfaces:**
- Consumes: `snapshot.trades` (existing `Trade[]`).

- [ ] **Step 1: Create the component**

Create `desktop/src/renderer/src/components/TradesTable.tsx`:

```tsx
import type { Trade } from "../../../lib/parse";

export default function TradesTable({ trades }: { trades: Trade[] }) {
  const recent = trades.slice(-30).reverse();
  if (!recent.length) return <div className="empty">No fills yet.</div>;
  return (
    <table>
      <thead>
        <tr><th>Time</th><th>Symbol</th><th>Side</th><th className="right">Qty</th><th className="right">Price</th><th className="right">Fee</th></tr>
      </thead>
      <tbody>
        {recent.map((t, i) => (
          <tr key={`${t.ts}-${i}`}>
            <td className="muted">{new Date(t.ts).toLocaleTimeString()}</td>
            <td>{t.symbol}</td>
            <td><span className={`badge ${t.side}`}>{t.side}</span></td>
            <td className="right">{t.qty.toFixed(6)}</td>
            <td className="right">${t.price.toFixed(2)}</td>
            <td className="right muted">${t.fee.toFixed(4)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Wire into App**

In `desktop/src/renderer/src/App.tsx`, import it:

```typescript
import TradesTable from "./components/TradesTable";
```

Add a Trades card to the grid (after the Decisions card):

```tsx
        <div className="card">
          <h2>Trades</h2>
          <TradesTable trades={snap.trades} />
        </div>
```

- [ ] **Step 3: Build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/TradesTable.tsx desktop/src/renderer/src/App.tsx
git commit -m "feat: dashboard trades table"
```

---

### Task 6: Backtest results chart

**Files:**
- Create: `desktop/src/renderer/src/components/BacktestChart.tsx`
- Modify: `desktop/src/renderer/src/App.tsx` (Backtest card)

**Interfaces:**
- Consumes: `snapshot.backtest` (`BacktestPoint[]`, Task 3).

- [ ] **Step 1: Create the component**

Create `desktop/src/renderer/src/components/BacktestChart.tsx`:

```tsx
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Legend } from "recharts";
import type { BacktestPoint } from "../../../lib/parse";

export default function BacktestChart({ points }: { points: BacktestPoint[] }) {
  if (!points.length)
    return <div className="empty">Run a backtest (<code>python -m engine.backtest …</code>) to see results here.</div>;
  const data = points.map((p, i) => ({ i, equity: p.equity, buyHold: p.buyHold }));
  const label = (n: string): string => (n === "equity" ? "strategy" : "buy & hold");
  return (
    <div className="chartbox">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
          <XAxis dataKey="i" hide />
          <YAxis stroke="#93a0bd" width={64} domain={["auto", "auto"]} tickFormatter={(v) => `$${Math.round(v)}`} />
          <Tooltip
            contentStyle={{ background: "#131a2e", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10, color: "#e8edf7" }}
            formatter={(v: number, n: string) => [`$${v.toFixed(2)}`, label(n)]}
          />
          <Legend formatter={(v: string) => label(v)} />
          <Line type="monotone" dataKey="equity" stroke="#7c8bff" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="buyHold" stroke="#93a0bd" strokeWidth={2} strokeDasharray="4 3" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 2: Wire into App**

In `desktop/src/renderer/src/App.tsx`, import it:

```typescript
import BacktestChart from "./components/BacktestChart";
```

Add a Backtest card to the grid (after the Sentiment card, span2):

```tsx
        <div className="card span2">
          <h2>Backtest</h2>
          <BacktestChart points={snap.backtest} />
        </div>
```

- [ ] **Step 3: Build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/BacktestChart.tsx desktop/src/renderer/src/App.tsx
git commit -m "feat: dashboard backtest results chart"
```

---

### Task 7: README + final verification

**Files:**
- Modify: `README.md`
- Test: full suites + Playwright

- [ ] **Step 1: Update README**

In `README.md`, extend the dashboard description (the Sentiment section mentions the panel) with a short note — find the paragraph describing the desktop dashboard and add:

> The dashboard also shows a **Status** strip (active strategy, exchange, leverage, shorting, funding rate + cumulative funding accrued, and risk limits — read from `data/status.json`), a **Trades** table (recent fills), and a **Backtest** chart (strategy vs buy-and-hold from `data/backtest_equity.csv`, populated by `python -m engine.backtest`).

- [ ] **Step 2: Full engine + desktop suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest green; build exit 0.

- [ ] **Step 3: Playwright visual verification**

Build the renderer, serve a harness with a representative snapshot (a `status` with leverage 5 / shorting on / funding 0.01%/8h / accrued −$1.23, a few `trades`, and a `backtest` curve), and screenshot at 1280 / 768 / 375 px. Confirm the Status strip chips, Trades table, and Backtest chart all render (plus their empty states with a second snapshot omitting those files), and mobile reflow holds. Clean up harness artifacts after.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document dashboard status strip, trades, and backtest view"
```

---

## Self-Review

**Spec coverage:**
- `State.funding_accrued` (persist) + bot accrual → Task 1 ✓
- `write_status` + bot writes resolved `status.json` each cycle → Task 2 ✓
- `parse.ts` `Status`/`BacktestPoint`/`parseBacktestCsv` + widened `Snapshot`; `status.ts` formatters; `snapshot.ts` reads → Task 3 ✓
- StatusStrip (mode + funding) → Task 4 ✓
- TradesTable → Task 5 ✓
- BacktestChart → Task 6 ✓
- README + Playwright → Task 7 ✓
- Engine-write-is-advisory, resolved mode, signed `funding_accrued`, backward-compat → Tasks 1 & 2 ✓
- Read-only / resilient reader (missing file → null/[]) → Task 3 (`readOr`) ✓

**Type/signature consistency:** `write_status(snapshot, data_dir)` — Task 2 defines, Task 2 bot calls ✓. `Status`/`RiskStatus`/`FundingStatus`/`BacktestPoint` — Task 3 defines, Tasks 4/6 consume; `status.json` shape written by Task 2 matches the `Status` type field names exactly (`risk.{allow_short,leverage,maintenance_margin_pct,funding_rate,funding_interval_hours,max_position_pct,stop_loss_pct}`, `funding.{accrued,last_funding_ts}`) ✓. `parseBacktestCsv`/`leverageMode`/`shortingLabel`/`fundingSummary`/`accruedLabel` — Task 3 defines + consumes ✓. `Snapshot` widening + `EMPTY` update co-located in Task 3 so the build stays green ✓.

**Placeholder scan:** none — every code step shows full code; component tasks gate on `npm run build`; the lib task carries the vitest assertions.
