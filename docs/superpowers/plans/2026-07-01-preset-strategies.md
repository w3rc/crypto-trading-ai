# Preset Trading Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four deterministic preset strategies (MA cross, MACD cross, RSI mean-reversion, Bollinger) and a dashboard dropdown to switch the active strategy live.

**Architecture:** Extend the existing `STRATEGIES` registry with pure functions; add a Bollinger indicator; add a `control.json` `strategy` override (twin of the mode override); expose a native `<select>` in the sidebar that writes it via a new IPC — mirroring the Mode toggle end-to-end.

**Tech Stack:** Python 3 (pandas, pydantic, pytest), Electron + React + TypeScript (vitest), Playwright for UI verification.

## Global Constraints

- **Long-only spot** presets — a `sell` returned while flat is nullified downstream by `broker.plan_order`; do NOT special-case it (matches `indicator_rule`).
- **Registry is the single source of truth** — `engine/strategies.py::STRATEGIES` keys are the canonical strategy ids: `hybrid`, `indicator_rule`, `sentiment_rule`, `ma_cross`, `macd_cross`, `rsi_reversion`, `bollinger`.
- **Overrides fail safe** — an unknown/corrupt `control.json` value must fall back to the config default, never raise.
- **Buy size** = `cfg.rules.buy_size`; **sell** = full exit (`size=1.0`).
- **No new dependencies.** Bollinger uses pandas `.rolling(20)` (`std` default `ddof=1`).
- **Native `<select>`**, not a custom widget.
- **Playwright harness** (Task 6): CommonJS `require("/home/silverion/projects/myhermes-ai/node_modules/playwright/index.js")`; build first (`npm run build`) then serve `desktop/out/renderer` via `python3 -m http.server 8124 --bind 127.0.0.1 --directory desktop/out/renderer`; stub `window.api` via `page.addInitScript(...)` BEFORE `page.goto`.
- Run Python tests with `python -m pytest`; dashboard unit tests with `npm test` (vitest) inside `desktop/`.

---

### Task 1: Bollinger indicator

**Files:**
- Modify: `engine/indicators.py` (the `compute_indicators` return dict)
- Test: `tests/test_indicators.py`

**Interfaces:**
- Produces: `compute_indicators(df)` return dict gains three float keys: `bb_mid`, `bb_upper`, `bb_lower` (used by Task 2's `bollinger`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_indicators.py`:

```python
def test_bollinger_bands_ordered_and_centered():
    f = compute_indicators(_df([100.0 + i for i in range(60)]))
    assert f["bb_upper"] > f["bb_mid"] > f["bb_lower"]
    assert f["bb_mid"] == pytest.approx(149.5)     # mean of last 20 closes (140..159)

def test_bollinger_flat_series_has_zero_width():
    f = compute_indicators(_df([100.0] * 60))
    assert f["bb_upper"] == f["bb_mid"] == f["bb_lower"] == 100.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_indicators.py -k bollinger -v`
Expected: FAIL with `KeyError: 'bb_upper'`.

- [ ] **Step 3: Add the Bollinger keys**

In `engine/indicators.py`, inside `compute_indicators`, compute the band before the `return` and add the three keys. The function currently ends:

```python
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=9, adjust=False).mean()
    bb_mid = close.rolling(20).mean().iloc[-1]
    bb_std = close.rolling(20).std().iloc[-1]     # ddof=1 (pandas default)
    return {
        "price": float(close.iloc[-1]),
        "rsi": float(_rsi(close).iloc[-1]),
        "macd": float(macd.iloc[-1]),
        "macd_signal": float(signal.iloc[-1]),
        "ma_fast": float(close.rolling(20).mean().iloc[-1]),
        "ma_slow": float(close.rolling(50).mean().iloc[-1]),
        "atr": float(_atr(df).iloc[-1]),
        "bb_mid": float(bb_mid),
        "bb_upper": float(bb_mid + 2 * bb_std),
        "bb_lower": float(bb_mid - 2 * bb_std),
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: PASS (all indicator tests).

- [ ] **Step 5: Commit**

```bash
git add engine/indicators.py tests/test_indicators.py
git commit -m "feat(engine): add Bollinger bands to compute_indicators"
```

---

### Task 2: Preset strategy functions

**Files:**
- Modify: `engine/strategies.py` (add four functions + extend `STRATEGIES`)
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `features` dict with `ma_fast`, `ma_slow`, `macd`, `macd_signal`, `rsi`, `price`, `bb_lower`, `bb_upper` (Task 1); `cfg.rules.buy_size`, `cfg.rules.rsi_buy`, `cfg.rules.rsi_sell`.
- Produces: `strategies.ma_cross`, `strategies.macd_cross`, `strategies.rsi_reversion`, `strategies.bollinger`, each `(features, position, cash, cfg) -> Decision`; all four added to `STRATEGIES` (consumed by Task 3's override validation and Task 4's id set).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_strategies.py` (reuses the existing `_feats` and `_ns` helpers; adds a bollinger-specific feats builder):

```python
def _feats_bb(price, lower, upper):
    return {"price": price, "bb_lower": lower, "bb_upper": upper,
            "rsi": 50, "macd": 0.0, "macd_signal": 0.0,
            "ma_fast": 100.0, "ma_slow": 100.0, "atr": 1.0}


def test_ma_cross_golden_buys():
    d = strategies.ma_cross(_feats(rsi=50, fast=101, slow=100), _FLAT, 1000.0, _ns(buy_size=0.4))
    assert d.action == "buy" and d.size == 0.4

def test_ma_cross_death_sells():
    d = strategies.ma_cross(_feats(rsi=50, fast=99, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_ma_cross_equal_holds():
    d = strategies.ma_cross(_feats(rsi=50, fast=100, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_macd_cross_bull_buys():
    d = strategies.macd_cross(_feats(rsi=50, macd=1, sig=0), _FLAT, 1000.0, _ns(buy_size=0.5))
    assert d.action == "buy" and d.size == 0.5

def test_macd_cross_bear_sells():
    d = strategies.macd_cross(_feats(rsi=50, macd=-1, sig=0), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_macd_cross_equal_holds():
    d = strategies.macd_cross(_feats(rsi=50, macd=0, sig=0), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_rsi_reversion_oversold_buys():
    d = strategies.rsi_reversion(_feats(rsi=25), _FLAT, 1000.0, _ns(buy_size=0.3))
    assert d.action == "buy" and d.size == 0.3

def test_rsi_reversion_overbought_sells():
    d = strategies.rsi_reversion(_feats(rsi=80), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_rsi_reversion_neutral_holds():
    d = strategies.rsi_reversion(_feats(rsi=50), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_bollinger_below_lower_buys():
    d = strategies.bollinger(_feats_bb(price=90, lower=95, upper=105), _FLAT, 1000.0, _ns(buy_size=0.6))
    assert d.action == "buy" and d.size == 0.6

def test_bollinger_above_upper_sells():
    d = strategies.bollinger(_feats_bb(price=110, lower=95, upper=105), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0

def test_bollinger_inside_holds():
    d = strategies.bollinger(_feats_bb(price=100, lower=95, upper=105), _FLAT, 1000.0, _ns())
    assert d.action == "hold"

def test_new_presets_registered():
    for name in ("ma_cross", "macd_cross", "rsi_reversion", "bollinger"):
        assert strategies.get(name) is getattr(strategies, name)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_strategies.py -k "ma_cross or macd_cross or rsi_reversion or bollinger or new_presets" -v`
Expected: FAIL with `AttributeError: module 'engine.strategies' has no attribute 'ma_cross'`.

- [ ] **Step 3: Add the four functions and register them**

In `engine/strategies.py`, add after `sentiment_rule` and before the `STRATEGIES` dict:

```python
def ma_cross(features, position, cash, cfg) -> Decision:
    """MA20/MA50 crossover trend-following. Long-only spot."""
    fast, slow = features["ma_fast"], features["ma_slow"]
    if fast > slow:
        return Decision(action="buy", size=cfg.rules.buy_size,
                        reason=f"ma:golden fast={fast:.2f} slow={slow:.2f}")
    if fast < slow:
        return Decision(action="sell", size=1.0,
                        reason=f"ma:death fast={fast:.2f} slow={slow:.2f}")
    return Decision(action="hold", reason=f"ma:flat fast={fast:.2f} slow={slow:.2f}")


def macd_cross(features, position, cash, cfg) -> Decision:
    """MACD/signal-line crossover momentum. Long-only spot."""
    macd, sig = features["macd"], features["macd_signal"]
    if macd > sig:
        return Decision(action="buy", size=cfg.rules.buy_size,
                        reason=f"macd:bull macd={macd:.4f} sig={sig:.4f}")
    if macd < sig:
        return Decision(action="sell", size=1.0,
                        reason=f"macd:bear macd={macd:.4f} sig={sig:.4f}")
    return Decision(action="hold", reason=f"macd:flat macd={macd:.4f} sig={sig:.4f}")


def rsi_reversion(features, position, cash, cfg) -> Decision:
    """RSI mean-reversion: buy oversold, sell overbought. Long-only spot."""
    rsi = features["rsi"]
    r = cfg.rules
    if rsi < r.rsi_buy:
        return Decision(action="buy", size=r.buy_size, reason=f"rsi:oversold rsi={rsi:.0f}")
    if rsi > r.rsi_sell:
        return Decision(action="sell", size=1.0, reason=f"rsi:overbought rsi={rsi:.0f}")
    return Decision(action="hold", reason=f"rsi:neutral rsi={rsi:.0f}")


def bollinger(features, position, cash, cfg) -> Decision:
    """Bollinger-band mean-reversion: buy at/below lower band, sell at/above upper. Long-only spot."""
    price, lower, upper = features["price"], features["bb_lower"], features["bb_upper"]
    if price <= lower:
        return Decision(action="buy", size=cfg.rules.buy_size,
                        reason=f"bb:lower price={price:.2f} lower={lower:.2f}")
    if price >= upper:
        return Decision(action="sell", size=1.0,
                        reason=f"bb:upper price={price:.2f} upper={upper:.2f}")
    return Decision(action="hold", reason=f"bb:inside price={price:.2f}")
```

Then replace the `STRATEGIES` dict:

```python
STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule,
              "sentiment_rule": sentiment_rule, "ma_cross": ma_cross,
              "macd_cross": macd_cross, "rsi_reversion": rsi_reversion,
              "bollinger": bollinger}
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: PASS (all strategy tests).

- [ ] **Step 5: Commit**

```bash
git add engine/strategies.py tests/test_strategies.py
git commit -m "feat(engine): add ma_cross/macd_cross/rsi_reversion/bollinger preset strategies"
```

---

### Task 3: control.json strategy override

**Files:**
- Modify: `engine/config.py` (add `_strategy_override`, import strategies, wire into `load_config`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `strategies.STRATEGIES` (Task 2) for validation.
- Produces: `_strategy_override(data_dir: str, default: str) -> str`; `Config.strategy` now reflects `control.json` when valid.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (reuses the existing `_toggle_yaml` helper, which omits `strategy:` so config defaults to `hybrid`):

```python
def test_control_json_overrides_strategy(tmp_path):
    (tmp_path / "control.json").write_text('{"strategy": "ma_cross"}')
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path))
    assert load_config(str(p)).strategy == "ma_cross"     # control.json wins

def test_control_json_invalid_strategy_ignored(tmp_path):
    (tmp_path / "control.json").write_text('{"strategy": "bogus"}')
    p = tmp_path / "c.yaml"; p.write_text(_toggle_yaml(tmp_path))
    assert load_config(str(p)).strategy == "hybrid"       # unregistered -> config default

def test_strategy_override_direct(tmp_path):
    from engine.config import _strategy_override
    (tmp_path / "control.json").write_text('{"strategy": "bollinger"}')
    assert _strategy_override(str(tmp_path), "hybrid") == "bollinger"
    (tmp_path / "control.json").write_text('{"strategy": "nope"}')
    assert _strategy_override(str(tmp_path), "hybrid") == "hybrid"           # not registered
    assert _strategy_override(str(tmp_path / "missing"), "hybrid") == "hybrid"  # no file
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_config.py -k strategy_override -v`
Expected: FAIL — `test_control_json_overrides_strategy` returns `hybrid` (override not wired) / `ImportError` for `_strategy_override`.

- [ ] **Step 3: Implement the override**

In `engine/config.py`, add to the top-level imports (after `import yaml`):

```python
from engine import strategies
```

Add the function next to `_auto_execute_override`:

```python
def _strategy_override(data_dir: str, default: str) -> str:
    """A registered strategy name in <data_dir>/control.json overrides config; fail-safe to default."""
    path = os.path.join(data_dir, "control.json")
    try:
        with open(path) as f:
            s = json.load(f).get("strategy")
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return default                      # missing / unreadable / bad JSON / non-dict
    return s if s in strategies.STRATEGIES else default
```

In `load_config`, replace the line:

```python
        strategy=raw.get("strategy", "hybrid"),
```

with:

```python
        strategy=_strategy_override(raw["data_dir"], raw.get("strategy", "hybrid")),
```

- [ ] **Step 4: Make two pre-existing non-hermetic config tests hermetic**

`test_load_config_defaults` and `test_strategy_and_rules_load` load the real `engine/config.yaml` against the real `data/` dir, so working-tree runtime overrides (`data/symbols.json`, and — once this feature ships — `data/control.json`'s `strategy`) leak in and break their assertions. This already fails on `main` when `data/symbols.json` exists. Apply the file's existing hermetic pattern (see `test_mode_defaults_paper`): run under an empty tmp cwd.

Replace:

```python
def test_load_config_defaults(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg = load_config("engine/config.yaml")
```

with:

```python
def test_load_config_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "engine", "config.yaml")
    monkeypatch.chdir(tmp_path)   # hermetic: real data/ overrides (symbols.json/control.json) don't leak in
    cfg = load_config(cfg_path)
```

Replace:

```python
def test_strategy_and_rules_load(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg = load_config("engine/config.yaml")
```

with:

```python
def test_strategy_and_rules_load(monkeypatch, tmp_path):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "engine", "config.yaml")
    monkeypatch.chdir(tmp_path)   # hermetic: control.json strategy override doesn't leak in
    cfg = load_config(cfg_path)
```

(`os` is already imported at the top of `tests/test_config.py`.)

- [ ] **Step 5: Run config tests**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS — new strategy-override tests plus the now-hermetic defaults tests.

- [ ] **Step 6: Full Python suite green**

Run: `python -m pytest -q`
Expected: `0 failed` — the pre-existing `test_load_config_defaults` failure (working-tree `data/symbols.json` override) is resolved by the Step 4 hermeticity fix.

- [ ] **Step 7: Commit**

```bash
git add engine/config.py tests/test_config.py
git commit -m "feat(engine): control.json strategy override + hermetic config default tests"
```

---

### Task 4: writeStrategy in control.ts

**Files:**
- Modify: `desktop/src/lib/control.ts`
- Test: `desktop/src/lib/control.test.ts`

**Interfaces:**
- Consumes: existing `_merge(dir, patch)`.
- Produces: `writeStrategy(dir: string, name: string): Promise<void>` (consumed by Task 5's IPC).

- [ ] **Step 1: Write the failing tests**

Add to `desktop/src/lib/control.test.ts` (extend the import on line 2 to include `writeStrategy`):

```typescript
test("writeStrategy writes {strategy} for a valid name", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeStrategy(d, "ma_cross");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ strategy: "ma_cross" });
});

test("writeStrategy rejects an invalid name and writes nothing", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await expect(writeStrategy(d, "bogus")).rejects.toThrow();
  expect(existsSync(join(d, "control.json"))).toBe(false);
});

test("writeStrategy preserves existing mode and auto_execute", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "live");
  await writeAutoExecute(d, true);
  await writeStrategy(d, "bollinger");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({
    mode: "live", auto_execute: true, strategy: "bollinger",
  });
});
```

Change line 2 to:

```typescript
import { writeControl, writeAutoExecute, writeStrategy } from "./control";
```

- [ ] **Step 2: Run to verify they fail**

Run (from `desktop/`): `npm test -- control.test.ts`
Expected: FAIL — `writeStrategy` is not exported.

- [ ] **Step 3: Implement writeStrategy**

In `desktop/src/lib/control.ts`, add the id set below the existing `VALID` set:

```typescript
const VALID_STRATEGIES = new Set([
  "hybrid", "indicator_rule", "sentiment_rule",
  "ma_cross", "macd_cross", "rsi_reversion", "bollinger",
]);
```

Add at the end of the file:

```typescript
export async function writeStrategy(dir: string, name: string): Promise<void> {
  if (!VALID_STRATEGIES.has(name)) throw new Error(`invalid strategy: ${name}`);
  await _merge(dir, { strategy: name });
}
```

- [ ] **Step 4: Run to verify they pass**

Run (from `desktop/`): `npm test -- control.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/control.ts desktop/src/lib/control.test.ts
git commit -m "feat(dashboard): writeStrategy control.json merge writer"
```

---

### Task 5: set-strategy IPC + preload

**Files:**
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts`

**Interfaces:**
- Consumes: `writeStrategy` (Task 4).
- Produces: `window.api.setStrategy(name: string)` (consumed by Task 6).

- [ ] **Step 1: Wire the main-process handler**

In `desktop/src/main/index.ts`, change the control import (line 5):

```typescript
import { writeControl, writeAutoExecute, writeStrategy } from "../lib/control";
```

Add the handler next to `set-mode` (after line 48):

```typescript
    ipcMain.handle("set-strategy", (_e, name: string) => writeStrategy(dataDir(), name));
```

- [ ] **Step 2: Expose it in preload**

In `desktop/src/preload/index.ts`, add to the `api` object (after `setAutoExecute`):

```typescript
  setStrategy: (name: string) => ipcRenderer.invoke("set-strategy", name),
```

- [ ] **Step 3: Verify the build typechecks**

Run (from `desktop/`): `npm run build`
Expected: build completes with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/main/index.ts desktop/src/preload/index.ts
git commit -m "feat(dashboard): set-strategy IPC + preload binding"
```

---

### Task 6: Sidebar strategy picker + Playwright verify

**Files:**
- Modify: `desktop/src/renderer/src/components/Sidebar.tsx`
- Modify: `desktop/src/renderer/src/index.css`
- Test: Playwright script (scratchpad, not committed)

**Interfaces:**
- Consumes: `window.api.setStrategy` (Task 5); `status.strategy` (already parsed).

- [ ] **Step 1: Add the strategy list + api type**

In `desktop/src/renderer/src/components/Sidebar.tsx`, add after the `MODES` const (line 20):

```typescript
const STRATEGIES: { id: string; label: string }[] = [
  { id: "hybrid", label: "AI (hybrid)" },
  { id: "indicator_rule", label: "Indicator rule" },
  { id: "sentiment_rule", label: "Sentiment rule" },
  { id: "ma_cross", label: "MA cross" },
  { id: "macd_cross", label: "MACD cross" },
  { id: "rsi_reversion", label: "RSI reversion" },
  { id: "bollinger", label: "Bollinger" },
];
```

Replace the `api` const (line 22) so it also types `setStrategy`:

```typescript
const api = (window as unknown as { api: {
  setMode?: (m: string) => Promise<void>;
  setStrategy?: (s: string) => Promise<void>;
} }).api;
```

- [ ] **Step 2: Add optimistic state + handler**

In the `Sidebar` component body, after the existing Mode `choose` block (after line 49), add:

```typescript
  const currentStrat = status?.strategy ?? "hybrid";
  const [pendingStrat, setPendingStrat] = useState<string | null>(null);
  useEffect(() => {
    if (pendingStrat && status?.strategy === pendingStrat) setPendingStrat(null);  // bot caught up
  }, [status?.strategy, pendingStrat]);
  const activeStrat = pendingStrat ?? currentStrat;

  const chooseStrat = (s: string): void => {
    if (s === activeStrat) return;
    setPendingStrat(s);
    void api?.setStrategy?.(s).catch(() => setPendingStrat(null));   // failed write -> drop optimistic
  };
```

- [ ] **Step 3: Render the picker**

In the JSX, add a second `rail-toggle` block immediately after the Mode block's closing `</div>` (after line 97, before `<div className="rail-foot">`):

```tsx
      <div className="rail-toggle">
        <div className="rail-toggle-label">Strategy</div>
        <select className="rail-select" value={activeStrat}
                onChange={(e) => chooseStrat(e.target.value)}>
          {STRATEGIES.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        {pendingStrat && pendingStrat !== currentStrat && <div className="rail-toggle-hint">applies next cycle</div>}
      </div>
```

- [ ] **Step 4: Add CSS**

In `desktop/src/renderer/src/index.css`, after the `.rail-toggle-hint` rule (line 96), add:

```css
.rail-select { width: 100%; background: var(--glass); border: 1px solid var(--glass-border); color: var(--text); font: inherit; font-size: 12px; padding: 7px 8px; border-radius: 8px; cursor: pointer; }
.rail-toggle + .rail-toggle { margin-top: 14px; }
```

- [ ] **Step 5: Build**

Run (from `desktop/`): `npm run build`
Expected: build completes, no TypeScript errors.

- [ ] **Step 6: Write the Playwright verification script**

Create `/tmp/claude-1000/-home-silverion-projects-cryptotrading-ai/e41c39d0-a903-4e00-95f4-b350495bad11/scratchpad/verify-strategy-picker.mjs`:

```javascript
const pw = require("/home/silverion/projects/myhermes-ai/node_modules/playwright/index.js");
const { chromium } = pw;

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await page.addInitScript(() => {
    const status = { ts: new Date().toISOString(), strategy: "hybrid", exchange: "binance",
      mode: "paper", halted: false, armed: false,
      risk: { allow_short: false, leverage: 1, maintenance_margin_pct: 0.005, funding_rate: 0,
        funding_interval_hours: 8, max_position_pct: 0.25, stop_loss_pct: 0.05 },
      funding: { accrued: 0, last_funding_ts: null } };
    window.__calls = [];
    window.api = {
      getSnapshot: async () => ({ state: null, trades: [], decisions: [], sentiment: null,
        status, backtest: [], pending: {} }),
      setStrategy: async (s) => { window.__calls.push(s); status.strategy = s; },
      setMode: async () => {},
    };
  });
  await page.goto("http://127.0.0.1:8124/index.html");
  await page.waitForSelector("select.rail-select");
  const initial = await page.$eval("select.rail-select", (el) => el.value);
  await page.selectOption("select.rail-select", "bollinger");   // awaits the change
  const calls = await page.evaluate(() => window.__calls);
  const after = await page.$eval("select.rail-select", (el) => el.value);
  await page.screenshot({ path: "scratchpad/strategy-picker.png" });
  await browser.close();
  const ok = initial === "hybrid" && calls.includes("bollinger") && after === "bollinger";
  console.log(JSON.stringify({ initial, calls, after, ok }));
  process.exit(ok ? 0 : 1);
})();
```

- [ ] **Step 7: Serve the build and run the script**

```bash
cd /home/silverion/projects/cryptotrading_ai
python3 -m http.server 8124 --bind 127.0.0.1 --directory desktop/out/renderer &
SERVER=$!
sleep 1
node scratchpad/verify-strategy-picker.mjs
RESULT=$?
kill $SERVER
exit $RESULT
```

Expected: JSON with `"ok": true` (`initial=hybrid`, `calls` includes `bollinger`, `after=bollinger`), exit 0, and `scratchpad/strategy-picker.png` shows the Strategy dropdown in the sidebar.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/renderer/src/components/Sidebar.tsx desktop/src/renderer/src/index.css
git commit -m "feat(dashboard): sidebar strategy picker (live-switchable)"
```

---

## Self-Review

**Spec coverage:**
- Bollinger indicator → Task 1 ✓
- Four preset strategies → Task 2 ✓
- control.json strategy override (fail-safe) → Task 3 ✓
- writeStrategy merge writer → Task 4 ✓
- set-strategy IPC + preload → Task 5 ✓
- Sidebar native `<select>` picker + status reflection → Task 6 ✓
- Testing (indicators, strategies, config, control.ts, Playwright) → covered across tasks ✓
- Acceptance criteria 1–4 → Tasks 3, 2, 6, and the Step-5 full-suite gate ✓

**Type consistency:** `bb_mid/bb_upper/bb_lower` produced in Task 1, consumed in Task 2 `bollinger`. `_strategy_override` signature identical in Task 3 code and test. `writeStrategy(dir, name)` consistent across Tasks 4/5. `setStrategy` consistent Tasks 5/6. Strategy id set identical in `STRATEGIES` (T2), `VALID_STRATEGIES` (T4), and the renderer `STRATEGIES` list (T6) — all seven ids match.

**Placeholder scan:** No TBD/TODO; all code blocks complete. The one intentional Playwright typo is flagged inline with the fix.
