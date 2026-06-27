# Sentiment Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the bot's per-source sentiment breakdown to `data/sentiment.json` each cycle and render it in the dashboard as a Sentiment panel (blended score + Fear/Greed label + gauge, per-source rows, active strategy).

**Architecture:** Engine — refactor the aggregator into a shared `_blend` helper + a new `breakdown()` (per-source + blended); the bot computes `breakdown` once per cycle (feeds the same blended value into features, unchanged) and writes `data/sentiment.json` via a fail-safe atomic `state.write_sentiment`. Dashboard — the snapshot reader picks up `sentiment.json`; a new `SentimentPanel` React component renders it using pure label/gauge helpers.

**Tech Stack:** Python 3.14 (engine), TypeScript + React + electron-vite + vitest (desktop). No new dependencies.

## Global Constraints

- **No new dependencies** (engine or desktop).
- **Trading behavior is unchanged:** the blended value injected into `features["sentiment"]` is identical to today's. `sentiment_rule`, `broker.plan_order`, `apply_fill`, `indicators`, `models` are untouched.
- **Fail-safe:** `breakdown()` never raises (per-source try/except backstop, same as the aggregator); `state.write_sentiment` failures are caught in the bot and logged — a sentiment or disk error never aborts a cycle.
- **`breakdown` and `aggregate_sentiment` share the `_blend` helper** so the blend can't drift; `aggregate_sentiment` becomes a thin wrapper returning blended-only (the backtest caller is unaffected).
- **`null` means an unavailable source** (no key / error / empty) — distinct from a real `0.0`.
- **Live-only:** the bot writes `sentiment.json`; backtests do not. The panel watches the running bot.
- **Dashboard stays read-only + resilient:** a missing/garbled `sentiment.json` → `null` → the panel shows "off", never crashes (same `readOr` pattern as the other files).
- `data/sentiment.json` is a generated runtime artifact — **gitignored**.
- Local commits OK (already authorized for this project). Do not push or open a PR without explicit go-ahead.

---

### Task 1: Engine — `_blend` + `breakdown` + `aggregate_sentiment` wrapper

**Files:**
- Modify: `engine/sentiment.py` (the aggregator section, ~lines 233-252)
- Test: `tests/test_sentiment.py`

**Interfaces:**
- Consumes: `SOURCES`, `_source_scores`, `_clamp`, `cfg.sentiment.weights` (existing).
- Produces:
  - `_blend(items) -> float` — weighted mean over present `(weight, score)` pairs, `0.0` if none, clamped.
  - `breakdown(symbols, cfg, backtest=False, ts_ms=None) -> dict` → `{sym: {"blended": float, "sources": {name: score|None}}}` (all four source keys always present; `None` = source didn't contribute).
  - `aggregate_sentiment(symbols, cfg, backtest=False, ts_ms=None) -> dict` → `{sym: blended}` (now a thin wrapper over `breakdown`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sentiment.py`:

```python
def test_breakdown_reports_per_source_and_blended(monkeypatch):
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 0.8 for x in s})
    monkeypatch.setitem(sentiment.SOURCES, "cryptopanic",
                        lambda s, c, backtest=False, ts_ms=None: {x: -0.4 for x in s})
    for name in ("reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    bd = sentiment.breakdown(["BTC/USDT"], _cfg())
    src = bd["BTC/USDT"]["sources"]
    assert src["fear_greed"] == 0.8
    assert src["cryptopanic"] == -0.4
    assert src["reddit"] is None and src["x_twitter"] is None   # absent -> None, not 0.0
    assert set(src) == {"fear_greed", "cryptopanic", "reddit", "x_twitter"}  # all keys present


def test_breakdown_blended_matches_aggregate(monkeypatch):
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 0.8 for x in s})
    monkeypatch.setitem(sentiment.SOURCES, "cryptopanic",
                        lambda s, c, backtest=False, ts_ms=None: {x: -0.4 for x in s})
    for name in ("reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    cfg = _cfg()
    bd = sentiment.breakdown(["BTC/USDT"], cfg)
    agg = sentiment.aggregate_sentiment(["BTC/USDT"], cfg)
    assert bd["BTC/USDT"]["blended"] == agg["BTC/USDT"]   # wrapper agrees with the primitive


def test_breakdown_survives_a_raising_source(monkeypatch):
    def boom(symbols, cfg, backtest=False, ts_ms=None):
        raise RuntimeError("source exploded")
    monkeypatch.setitem(sentiment.SOURCES, "cryptopanic", boom)
    monkeypatch.setitem(sentiment.SOURCES, "fear_greed",
                        lambda s, c, backtest=False, ts_ms=None: {x: 0.6 for x in s})
    for name in ("reddit", "x_twitter"):
        monkeypatch.setitem(sentiment.SOURCES, name,
                            lambda s, c, backtest=False, ts_ms=None: {})
    bd = sentiment.breakdown(["BTC/USDT"], _cfg())          # must not raise
    assert bd["BTC/USDT"]["blended"] == pytest.approx(0.6)  # healthy source still counts
    assert bd["BTC/USDT"]["sources"]["cryptopanic"] is None  # the exploding source drops out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sentiment.py -k breakdown -v`
Expected: FAIL — `AttributeError: module 'engine.sentiment' has no attribute 'breakdown'`

- [ ] **Step 3: Refactor the aggregator into `_blend` + `breakdown` + wrapper**

In `engine/sentiment.py`, REPLACE the current `aggregate_sentiment` function (the block that starts `def aggregate_sentiment(symbols, cfg, backtest=False, ts_ms=None):` and ends with its `return out`) with:

```python
def _blend(items):
    """Weighted mean over present (weight, score) pairs; 0.0 if none; clamped."""
    tw = sum(w for w, _ in items)
    return _clamp(sum(w * sc for w, sc in items) / tw) if tw else 0.0


def breakdown(symbols, cfg, backtest=False, ts_ms=None):
    """Per-source scores + the weighted blend per symbol. Never raises.

    Returns {sym: {"blended": float, "sources": {name: score|None}}}; a source
    that did not contribute a score for a symbol is reported as None (distinct
    from a real 0.0).
    """
    weights = cfg.sentiment.weights
    contrib = {s: [] for s in symbols}                              # {sym: [(weight, score)]}
    per_source = {s: {name: None for name in SOURCES} for s in symbols}
    for name, fn in SOURCES.items():
        w = weights.get(name, 0.0)
        if w <= 0:
            continue
        try:
            scores = _source_scores(name, fn, symbols, cfg, backtest, ts_ms)
            for sym, score in scores.items():
                if sym in contrib:
                    contrib[sym].append((w, score))
                    per_source[sym][name] = score
        except Exception:
            continue   # a source that blows up just drops out; breakdown never raises
    return {sym: {"blended": _blend(contrib[sym]), "sources": per_source[sym]}
            for sym in symbols}


def aggregate_sentiment(symbols, cfg, backtest=False, ts_ms=None):
    """Blended score per symbol — a thin wrapper over breakdown()."""
    return {sym: bd["blended"]
            for sym, bd in breakdown(symbols, cfg, backtest, ts_ms).items()}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sentiment.py -v`
Expected: PASS (all sentiment tests — the new `breakdown` tests AND every existing `aggregate_sentiment` test, since the blend behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/sentiment.py tests/test_sentiment.py
git commit -m "feat(sentiment-panel): breakdown() per-source scores + shared _blend helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Engine — `state.write_sentiment` + gitignore

**Files:**
- Modify: `engine/state.py`
- Modify: `.gitignore`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `write_sentiment(snapshot: dict, data_dir: str) -> None` — atomic JSON write to `data/sentiment.json`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_state.py`:

```python
def test_write_sentiment_atomic_json(tmp_path):
    from engine.state import write_sentiment
    import json
    snap = {"ts": "2026-06-26T00:00:00+00:00", "strategy": "sentiment_rule",
            "symbols": {"BTC/USDT": {"blended": -0.62,
                                     "sources": {"fear_greed": -0.78, "cryptopanic": None,
                                                 "reddit": None, "x_twitter": None}}}}
    write_sentiment(snap, str(tmp_path))
    path = tmp_path / "sentiment.json"
    assert path.exists()
    loaded = json.loads(path.read_text())
    assert loaded["strategy"] == "sentiment_rule"
    assert loaded["symbols"]["BTC/USDT"]["blended"] == -0.62
    assert loaded["symbols"]["BTC/USDT"]["sources"]["cryptopanic"] is None
    assert not (tmp_path / "sentiment.json.tmp").exists()   # temp cleaned up (atomic replace)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -k write_sentiment -v`
Expected: FAIL — `ImportError: cannot import name 'write_sentiment'`

- [ ] **Step 3: Implement `write_sentiment`**

In `engine/state.py`, add after `save_state_atomic` (it mirrors that function's temp-then-`os.replace` pattern):

```python
def write_sentiment(snapshot: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "sentiment.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snapshot, f, indent=2)
    os.replace(tmp, path)                   # atomic on POSIX
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Gitignore the generated file**

In `.gitignore`, add `data/sentiment.json` after the `data/bot.lock` line:

```
data/sentiment.json
```

- [ ] **Step 6: Commit**

```bash
git add engine/state.py tests/test_state.py .gitignore
git commit -m "feat(sentiment-panel): atomic write_sentiment snapshot + gitignore

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Engine — bot writes the sentiment snapshot

**Files:**
- Modify: `engine/bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `sentiment.breakdown` (Task 1), `state.write_sentiment` (Task 2), `cfg.sentiment.enabled`, `cfg.strategy`.
- Produces: each cycle writes `data/sentiment.json` (when enabled); `features["sentiment"]` is the blended value (unchanged behavior).

- [ ] **Step 1: Update + add the tests**

In `tests/test_bot.py`, the two existing sentiment tests currently monkeypatch `aggregate_sentiment`. REPLACE them (the bot now calls `breakdown`) and ADD two snapshot tests:

```python
def test_sentiment_injected_into_features(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "breakdown",
                        lambda symbols, c: {"BTC/USDT": {"blended": 0.42, "sources": {}}})
    seen = {}

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    bot.run_once(cfg, market=FakeMarket(), strategy=capture)
    assert seen["sentiment"] == 0.42


def test_sentiment_absent_symbol_is_neutral(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "breakdown", lambda symbols, c: {})
    seen = {}

    def capture(features, position, cash, c):
        seen.update(features)
        return Decision(action="hold")

    bot.run_once(cfg, market=FakeMarket(), strategy=capture)
    assert seen["sentiment"] == 0.0


def test_sentiment_snapshot_written(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg.sentiment = SentimentConfig(enabled=True)
    monkeypatch.setattr(bot.sentiment_mod, "breakdown",
                        lambda symbols, c: {"BTC/USDT": {"blended": -0.3,
                                                         "sources": {"fear_greed": -0.3}}})
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "sentiment.json").read_text())
    assert data["symbols"]["BTC/USDT"]["blended"] == -0.3
    assert "strategy" in data and "ts" in data


def test_sentiment_disabled_writes_no_file(tmp_path):
    cfg = _cfg(tmp_path)   # enabled=False by default in _cfg
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    assert not (tmp_path / "sentiment.json").exists()
```

(`_json` is already imported at the top of `tests/test_bot.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bot.py -k sentiment -v`
Expected: FAIL — `test_sentiment_snapshot_written` fails (no `data/sentiment.json` is written yet; `FileNotFoundError` on the read). The two injection tests may already pass before Step 3 — `aggregate_sentiment` is a thin wrapper over the now-monkeypatched `breakdown`, so the blended value is unchanged (that is the point: trading behavior is identical). The snapshot write is the new behavior this task drives to green.

- [ ] **Step 3: Wire the bot to `breakdown` + write the snapshot**

In `engine/bot.py`:

Replace the sentiment computation (currently lines 25-26):

```python
        sent = (sentiment_mod.aggregate_sentiment(cfg.symbols, cfg)
                if cfg.sentiment.enabled else {})
```

with:

```python
        bd = (sentiment_mod.breakdown(cfg.symbols, cfg)
              if cfg.sentiment.enabled else {})
```

Replace the feature-injection line (currently line 41):

```python
            feats["sentiment"] = sent.get(sym, 0.0)
```

with:

```python
            feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)
```

Add the snapshot write right after the `for sym in cfg.symbols:` loop ends and before the `if prices:` block:

```python
        if cfg.sentiment.enabled:
            try:
                state_mod.write_sentiment(
                    {"ts": ts, "strategy": cfg.strategy, "symbols": bd}, cfg.data_dir)
            except Exception as e:                  # advisory: a write error never aborts the cycle
                log.warning("sentiment snapshot write failed: %s", e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bot.py -v`
Expected: PASS (all bot tests — existing ones still offline via `enabled=False`, the four sentiment tests green).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all engine tests).

- [ ] **Step 6: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat(sentiment-panel): bot computes breakdown + writes sentiment.json each cycle

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Dashboard — parse + read `sentiment.json`

**Files:**
- Modify: `desktop/src/lib/parse.ts`
- Modify: `desktop/src/lib/snapshot.ts`
- Modify: `desktop/src/renderer/src/App.tsx` (the `EMPTY` constant only — keeps the renderer compiling now that `Snapshot` requires `sentiment`)
- Test: `desktop/src/lib/parse.test.ts`, `desktop/src/lib/snapshot.test.ts`

**Interfaces:**
- Produces:
  - `SourceScores`, `SymbolSentiment`, `SentimentSnapshot` types; `Snapshot` gains `sentiment: SentimentSnapshot | null`.
  - `parseSentiment(text: string): SentimentSnapshot`.

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/lib/parse.test.ts`:

```ts
import { parseSentiment } from "./parse";

test("parseSentiment round-trips a snapshot", () => {
  const json = JSON.stringify({
    ts: "2026-06-26T00:00:00+00:00", strategy: "sentiment_rule",
    symbols: { "BTC/USDT": { blended: -0.62,
      sources: { fear_greed: -0.78, cryptopanic: null, reddit: null, x_twitter: null } } },
  });
  const s = parseSentiment(json);
  expect(s.strategy).toBe("sentiment_rule");
  expect(s.symbols["BTC/USDT"].blended).toBe(-0.62);
  expect(s.symbols["BTC/USDT"].sources.fear_greed).toBe(-0.78);
  expect(s.symbols["BTC/USDT"].sources.reddit).toBeNull();
});
```

Append a new test to `desktop/src/lib/snapshot.test.ts`:

```ts
test("readSnapshot reads sentiment.json, null when absent", async () => {
  const dir = mkdtempSync(join(tmpdir(), "snap-sent-"));
  writeFileSync(join(dir, "sentiment.json"), JSON.stringify({
    ts: "t1", strategy: "sentiment_rule",
    symbols: { "BTC/USDT": { blended: 0.2,
      sources: { fear_greed: 0.2, cryptopanic: null, reddit: null, x_twitter: null } } },
  }));
  const snap = await readSnapshot(dir);
  expect(snap.sentiment?.strategy).toBe("sentiment_rule");
  expect(snap.sentiment?.symbols["BTC/USDT"].blended).toBe(0.2);
  rmSync(dir, { recursive: true, force: true });

  const empty = mkdtempSync(join(tmpdir(), "snap-nosent-"));
  expect((await readSnapshot(empty)).sentiment).toBeNull();   // missing file -> null
  rmSync(empty, { recursive: true, force: true });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `desktop/`): `npm test`
Expected: FAIL — `parseSentiment` is not exported / `snap.sentiment` is undefined.

- [ ] **Step 3: Add the types + parser + reader**

In `desktop/src/lib/parse.ts`, add after the existing type exports:

```ts
export type SourceScores = { fear_greed: number | null; cryptopanic: number | null;
                             reddit: number | null; x_twitter: number | null };
export type SymbolSentiment = { blended: number; sources: SourceScores };
export type SentimentSnapshot = { ts: string; strategy: string;
                                  symbols: Record<string, SymbolSentiment> };
```

Change the `Snapshot` type to include sentiment:

```ts
export type Snapshot = { state: State | null; trades: Trade[]; decisions: Decision[];
                         sentiment: SentimentSnapshot | null };
```

Add the parser at the end of `parse.ts`:

```ts
export function parseSentiment(text: string): SentimentSnapshot {
  return JSON.parse(text) as SentimentSnapshot;
}
```

In `desktop/src/lib/snapshot.ts`, update the import and `readSnapshot`:

```ts
import { parseTradesCsv, parseDecisions, parseSentiment, Snapshot, State, SentimentSnapshot } from "./parse";
```

```ts
export async function readSnapshot(dir: string): Promise<Snapshot> {
  const state = await readOr<State | null>(join(dir, "state.json"), null, (s) => JSON.parse(s) as State);
  const trades = await readOr(join(dir, "trades.csv"), [], parseTradesCsv);
  const decisions = await readOr(join(dir, "decisions.jsonl"), [], parseDecisions);
  const sentiment = await readOr<SentimentSnapshot | null>(join(dir, "sentiment.json"), null, parseSentiment);
  return { state, trades, decisions, sentiment };
}
```

In `desktop/src/renderer/src/App.tsx`, update the `EMPTY` constant so the renderer still compiles against the widened `Snapshot` type (this is the only App.tsx change in this task — the panel itself comes in Task 6):

```tsx
const EMPTY: Snapshot = { state: null, trades: [], decisions: [], sentiment: null };
```

- [ ] **Step 4: Run tests + build to verify**

Run (from `desktop/`): `npm test`
Expected: PASS (all vitest tests).

Run (from `desktop/`): `npm run build`
Expected: build succeeds (the widened `Snapshot` type compiles — `EMPTY` now includes `sentiment`).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/snapshot.ts desktop/src/lib/parse.test.ts desktop/src/lib/snapshot.test.ts desktop/src/renderer/src/App.tsx
git commit -m "feat(sentiment-panel): parse + read sentiment.json into the dashboard snapshot

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Dashboard — sentiment label/gauge helpers

**Files:**
- Create: `desktop/src/lib/sentiment.ts`
- Test: `desktop/src/lib/sentiment.test.ts`

**Interfaces:**
- Produces:
  - `sentimentLabel(score: number): string` — Fear/Greed band.
  - `gaugePct(score: number): number` — maps `[-1, 1]` → `[0, 100]`, clamped.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/lib/sentiment.test.ts`:

```ts
import { test, expect } from "vitest";
import { sentimentLabel, gaugePct } from "./sentiment";

test("sentimentLabel bands", () => {
  expect(sentimentLabel(-0.8)).toBe("Extreme Fear");
  expect(sentimentLabel(-0.5)).toBe("Extreme Fear");   // boundary: <= -0.5
  expect(sentimentLabel(-0.3)).toBe("Fear");
  expect(sentimentLabel(0)).toBe("Neutral");
  expect(sentimentLabel(0.15)).toBe("Neutral");        // boundary: <= 0.15
  expect(sentimentLabel(0.3)).toBe("Greed");
  expect(sentimentLabel(0.8)).toBe("Extreme Greed");
});

test("gaugePct maps and clamps", () => {
  expect(gaugePct(-1)).toBe(0);
  expect(gaugePct(0)).toBe(50);
  expect(gaugePct(1)).toBe(100);
  expect(gaugePct(-5)).toBe(0);    // clamped
  expect(gaugePct(5)).toBe(100);   // clamped
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `desktop/`): `npm test`
Expected: FAIL — `Cannot find module './sentiment'`.

- [ ] **Step 3: Implement the helpers**

Create `desktop/src/lib/sentiment.ts`:

```ts
export function sentimentLabel(score: number): string {
  if (score <= -0.5) return "Extreme Fear";
  if (score < -0.15) return "Fear";
  if (score <= 0.15) return "Neutral";
  if (score < 0.5) return "Greed";
  return "Extreme Greed";
}

export function gaugePct(score: number): number {
  return Math.max(0, Math.min(100, ((score + 1) / 2) * 100));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `desktop/`): `npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/sentiment.ts desktop/src/lib/sentiment.test.ts
git commit -m "feat(sentiment-panel): pure label/gauge helpers for the sentiment UI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Dashboard — `SentimentPanel` component + App card + styles + docs

**Files:**
- Create: `desktop/src/renderer/src/components/SentimentPanel.tsx`
- Modify: `desktop/src/renderer/src/App.tsx`
- Modify: `desktop/src/renderer/src/index.css`
- Modify: `README.md`

**Interfaces:**
- Consumes: `SentimentSnapshot` (Task 4), `sentimentLabel`/`gaugePct` (Task 5).

This task is verified by a clean production build (`npm run build`); the visual rendering is confirmed by the controller via Playwright after the task (the existing dashboard pattern — components are visually verified, pure logic is unit-tested in Tasks 4-5).

- [ ] **Step 1: Create the component**

Create `desktop/src/renderer/src/components/SentimentPanel.tsx`:

```tsx
import type { SentimentSnapshot, SourceScores } from "../../../lib/parse";
import { sentimentLabel, gaugePct } from "../../../lib/sentiment";

const SOURCE_ROWS: [keyof SourceScores, string][] = [
  ["fear_greed", "F&G"], ["cryptopanic", "news"], ["reddit", "reddit"], ["x_twitter", "X"],
];

function fmt(v: number | null): string {
  return v === null ? "—" : (v >= 0 ? "+" : "") + v.toFixed(2);
}

function color(score: number): string {
  return score > 0.15 ? "var(--up)" : score < -0.15 ? "var(--down)" : "var(--muted)";
}

export default function SentimentPanel({ sentiment }: { sentiment: SentimentSnapshot | null }) {
  if (!sentiment) return <div className="empty">Sentiment off.</div>;
  const syms = Object.entries(sentiment.symbols);
  if (!syms.length) return <div className="empty">No sentiment yet.</div>;
  return (
    <div>
      {syms.map(([sym, s]) => (
        <div className="sent-row" key={sym}>
          <div className="sent-head">
            <span>{sym}</span>
            <span style={{ color: color(s.blended) }}>{fmt(s.blended)} · {sentimentLabel(s.blended)}</span>
          </div>
          <div className="gauge"><div className="gauge-marker" style={{ left: `${gaugePct(s.blended)}%` }} /></div>
          <div className="sent-sources">
            {SOURCE_ROWS.map(([k, label]) => (
              <span className="sent-src" key={k}>{label} <b>{fmt(s.sources[k])}</b></span>
            ))}
          </div>
        </div>
      ))}
      <div className="muted sent-strategy">strategy: {sentiment.strategy}</div>
    </div>
  );
}
```

- [ ] **Step 2: Render it in `App.tsx`**

Add the import alongside the other component imports:

```tsx
import SentimentPanel from "./components/SentimentPanel";
```

(The `EMPTY` constant already includes `sentiment: null` from Task 4.)

Add a new card after the Decisions card (before the closing `</div>` of `.grid`):

```tsx
        <div className="card span2">
          <h2>Sentiment</h2>
          <SentimentPanel sentiment={snap.sentiment} />
        </div>
```

- [ ] **Step 3: Add the styles**

Append to `desktop/src/renderer/src/index.css`:

```css
.sent-row { padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.06); }
.sent-row:last-of-type { border-bottom: none; }
.sent-head { display: flex; justify-content: space-between; font-size: 14px; font-weight: 600; }
.gauge { position: relative; height: 8px; border-radius: 999px; margin: 8px 0;
  background: linear-gradient(90deg, var(--down), var(--muted) 50%, var(--up)); }
.gauge-marker { position: absolute; top: -2px; width: 3px; height: 12px; border-radius: 2px;
  background: var(--text); transform: translateX(-50%); }
.sent-sources { display: flex; gap: 18px; flex-wrap: wrap; font-size: 13px; color: var(--muted); }
.sent-src b { color: var(--text); font-weight: 600; }
.sent-strategy { margin-top: 12px; font-size: 12px; }
```

- [ ] **Step 4: Build to verify it compiles**

Run (from `desktop/`): `npm run build`
Expected: build succeeds (TypeScript + Vite, no type errors).

- [ ] **Step 5: Run the desktop test suite**

Run (from `desktop/`): `npm test`
Expected: PASS (all vitest tests — unchanged from Tasks 4-5, confirming no regressions).

- [ ] **Step 6: Add the README note**

In `README.md`, add to the "Sentiment" section a line noting the dashboard panel:

```markdown
The desktop dashboard shows a **Sentiment** panel — per symbol it renders the blended
score (Fear/Greed label + gauge), the per-source breakdown (`F&G` / `news` / `reddit` /
`X`, with `—` for sources without a key), and the active strategy. It reads
`data/sentiment.json`, which the bot writes each cycle.
```

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/src/components/SentimentPanel.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/index.css README.md
git commit -m "feat(sentiment-panel): SentimentPanel component + dashboard card + styles

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the reviewer

- **Trading is untouched:** `breakdown()[sym]["blended"]` is the same number the old `aggregate_sentiment(...)[sym]` produced (the wrapper proves it via `test_breakdown_blended_matches_aggregate`). The bot only additionally *persists* the breakdown.
- **Fail-safe everywhere:** `breakdown` keeps the per-source try/except backstop (never raises); the bot's `write_sentiment` call is wrapped so a disk error logs and continues.
- **Dashboard resilience:** `sentiment.json` is read through the same `readOr` as the other files — missing/garbled → `null` → the panel shows "Sentiment off."
- **Visual verification of Task 6** is done by the controller with Playwright at 1280/768/375 (the dashboard's components are visually verified, not unit-rendered — there is no React test renderer configured).
