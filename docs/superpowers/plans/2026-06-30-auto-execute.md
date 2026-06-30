# Auto-Execute Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auto-execute toggle (default OFF) — when off, the bot proposes trades as pending suggestions the user manually Executes/Dismisses from the dashboard; Execute runs the stored decision through the same execution path and may place a real order in live+armed.

**Architecture:** The bot's cycle, when `auto_execute` is off, writes each non-hold *strategy* decision to `data/pending.json` instead of executing (a stop-loss `force_close` still always executes). Clicking Execute spawns `python -m engine.execute SYMBOL`, which calls the same `run_once` scoped to one symbol with the stored decision **forced** in place of the strategy. That manual spawn is the one engine spawn that is NOT pinned to `LIVE_TRADING_ARMED="no"`, so it inherits the operator's real arm; the engine still enforces the two-switch.

**Tech Stack:** Python 3 (engine, pytest), Electron + React + TypeScript (desktop, vitest), Playwright CLI for UI verification.

## Global Constraints

- **Default `auto_execute` is OFF (manual by default).** No `control.json` key / no config value → manual.
- **A risk `force_close` (stop-loss / liquidation) ALWAYS executes — it is never deferred to pending**, regardless of `auto_execute`. Deferral applies only to strategy / forced decisions.
- **`create_order` (engine/market.py) stays the single order function with a single caller (`_run_live`).** Re-verify at the end: `create_order` appears only as its def + the ccxt call + the log + the one `_run_live` caller; `cancel_order`/`withdraw` = 0 grep hits.
- **`pinnedEnv` stays applied to `runBot`/`runBacktest`. `executeSuggestion` is the ONLY un-pinned engine spawn** (`spawnEngineArmed`); it must be reachable only from the `execute-suggestion` IPC.
- `Decision` is a **pydantic** model — `size` is auto-clamped to `[0.0, 1.0]`.
- The engine decision log file is `data/decisions.jsonl` (JSON-lines), not `.json`.
- `data/pending.json` is a runtime override → add it to `.gitignore`.
- TDD: write the failing test first every step; keep the full suite green.
- Engine tests reuse the helper *patterns* in `tests/test_bot.py` (`_cfg`, `_df`, `FakeMarket`, `_LiveMarket`, `_strat`). `tests/` is NOT a Python package — do not cross-import between test modules; copy the small fakes into a new test file when needed.
- vitest currently globs only `src/lib/**/*.test.ts`; Task 7 extends it to cover `src/main/`.
- The renderer stylesheet is `desktop/src/renderer/src/index.css` (defines `.card`, `.bt-run`, `.muted`, `--up`/`--down` vars).
- **Playwright harness (Tasks 8–9 verify steps):** CommonJS import `const pw = require("/home/silverion/projects/myhermes-ai/node_modules/playwright/index.js"); const { chromium } = pw;`. Serve the built renderer with `python3 -m http.server 8123 --bind 127.0.0.1` from `desktop/out/renderer` (run `npm run build` first). Stub `window.api` via `page.addInitScript(...)` BEFORE navigating (so the stub exists when the bundle loads). Screenshot at 1280 / 768 / 375 into the scratchpad dir. Confirm Playwright hit the fresh build, not a stale port.

---

### Task 1: Engine — `auto_execute` config flag

**Files:**
- Modify: `engine/config.py` (add `_auto_execute_override`, `Config.auto_execute`, wire into `load_config`)
- Modify: `engine/config.yaml` (add `auto_execute: false`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config.auto_execute: bool` (default `False`); `_auto_execute_override(data_dir: str, default: bool) -> bool` reading `data/control.json`'s `auto_execute` key.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
from engine.config import _auto_execute_override


def test_auto_execute_override_default_when_missing(tmp_path):
    assert _auto_execute_override(str(tmp_path), False) is False
    assert _auto_execute_override(str(tmp_path), True) is True


def test_auto_execute_override_reads_bool(tmp_path):
    (tmp_path / "control.json").write_text('{"auto_execute": true}')
    assert _auto_execute_override(str(tmp_path), False) is True
    (tmp_path / "control.json").write_text('{"auto_execute": false}')
    assert _auto_execute_override(str(tmp_path), True) is False


def test_auto_execute_override_non_bool_falls_back(tmp_path):
    (tmp_path / "control.json").write_text('{"auto_execute": "yes"}')   # not a bool
    assert _auto_execute_override(str(tmp_path), False) is False
    (tmp_path / "control.json").write_text("not json")
    assert _auto_execute_override(str(tmp_path), True) is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_config.py -k auto_execute -v`
Expected: FAIL with `ImportError` / `cannot import name '_auto_execute_override'`.

- [ ] **Step 3: Implement**

In `engine/config.py`, add after `_mode_override` (just before `_SYMBOL_RE`):

```python
def _auto_execute_override(data_dir: str, default: bool) -> bool:
    """A bool `auto_execute` in <data_dir>/control.json overrides config; fail-safe to default."""
    path = os.path.join(data_dir, "control.json")
    try:
        with open(path) as f:
            v = json.load(f).get("auto_execute")
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return default                      # missing / unreadable / bad JSON / non-dict
    return v if isinstance(v, bool) else default
```

Add the field to the `Config` dataclass (after `interval_seconds: int = 900`):

```python
    auto_execute: bool = False
```

Wire it in `load_config`'s `Config(...)` return (add after the `mode=...` line):

```python
        auto_execute=_auto_execute_override(raw["data_dir"], bool(raw.get("auto_execute", False))),
```

In `engine/config.yaml`, add under `mode: paper` (a sibling top-level key):

```yaml
auto_execute: false   # OFF = bot proposes; you Execute/Dismiss each trade. Dashboard toggles this.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the existing ones).

- [ ] **Step 5: Commit**

```bash
git add engine/config.py engine/config.yaml tests/test_config.py
git commit -m "feat(engine): auto_execute config flag (default off) via control.json override"
```

---

### Task 2: Engine — pending suggestion I/O

**Files:**
- Modify: `engine/state.py` (add `load_pending`, `save_pending`)
- Modify: `.gitignore` (add `data/pending.json`)
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `load_pending(data_dir: str) -> dict` (`{}` on missing/corrupt/non-dict); `save_pending(pending: dict, data_dir: str) -> None` (atomic write to `data/pending.json`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_state.py`:

```python
from engine.state import load_pending, save_pending


def test_pending_round_trip(tmp_path):
    p = {"ETH/USDT": {"ts": "t", "action": "sell", "size": 1.0, "reason": "r", "price": 1583.35}}
    save_pending(p, str(tmp_path))
    assert load_pending(str(tmp_path)) == p


def test_load_pending_missing_is_empty(tmp_path):
    assert load_pending(str(tmp_path)) == {}


def test_load_pending_corrupt_is_empty(tmp_path):
    (tmp_path / "pending.json").write_text("{not json")
    assert load_pending(str(tmp_path)) == {}


def test_load_pending_non_dict_is_empty(tmp_path):
    (tmp_path / "pending.json").write_text("[1, 2, 3]")
    assert load_pending(str(tmp_path)) == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_state.py -k pending -v`
Expected: FAIL with `ImportError: cannot import name 'load_pending'`.

- [ ] **Step 3: Implement**

In `engine/state.py`, add after `save_live_meta` (mirrors the existing `load_live_meta` / atomic-write pattern):

```python
def _pending_path(data_dir: str) -> str:
    return os.path.join(data_dir, "pending.json")


def load_pending(data_dir: str) -> dict:
    """Deferred suggestions {symbol: {...}} for manual mode; missing/corrupt/non-dict -> {}."""
    path = _pending_path(data_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_pending(pending: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = _pending_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(pending, f, indent=2)
    os.replace(tmp, path)                       # atomic on POSIX
```

In `.gitignore`, add after the `data/live_meta.json` line:

```
data/pending.json
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/state.py .gitignore tests/test_state.py
git commit -m "feat(engine): pending.json load/save helpers (fail-safe, atomic)"
```

---

### Task 3: Engine — defer strategy decisions to pending in the cycle

**Files:**
- Modify: `engine/bot.py` (`_record_pending` helper; `run_once`/`_run_shadow`/`_run_live` deferral + `only_symbol`/`forced_decision` params; `_status_payload` carries `auto_execute`)
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `state_mod.load_pending`/`save_pending` (Task 2); `cfg.auto_execute` (Task 1).
- Produces: `run_once(cfg=None, market=None, strategy=None, only_symbol=None, forced_decision=None)`; `_run_live(cfg, market, strategy, only_symbol=None, forced_decision=None)`; `_record_pending(pending, sym, order, decision, price, ts)`. `status.json` now carries `"auto_execute"`.

> Read `engine/bot.py` fully before editing. The edits below are anchored to current code; apply each precisely.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_bot.py` (helpers `_cfg`, `_df`, `FakeMarket`, `_LiveMarket`, `_strat` already exist in that file):

```python
def test_paper_auto_off_defers_to_pending(tmp_path):
    cfg = _cfg(tmp_path); cfg.auto_execute = False
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    # no fill happened
    assert not (tmp_path / "trades.csv").exists()
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty == 0.0
    # decision logged as not executed
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["action"] == "buy" and rec["executed"] is False
    # suggestion recorded
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert pend["BTC/USDT"]["action"] == "buy" and pend["BTC/USDT"]["size"] == 1.0


def test_paper_auto_on_executes(tmp_path):
    cfg = _cfg(tmp_path); cfg.auto_execute = True
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0                 # auto-on still trades
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend                            # nothing pending


def test_paper_auto_off_hold_clears_pending(tmp_path):
    cfg = _cfg(tmp_path); cfg.auto_execute = False
    save_pending({"BTC/USDT": {"ts": "t", "action": "buy", "size": 1.0, "reason": "r", "price": 1.0}},
                 str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend                            # a HOLD clears a stale suggestion


def test_paper_forced_decision_executes_despite_auto_off(tmp_path):
    cfg = _cfg(tmp_path); cfg.auto_execute = False
    # strategy says hold; forced says buy -> forced wins AND executes (bypasses deferral)
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")),
                 only_symbol="BTC/USDT", forced_decision=Decision(action="buy", size=1.0))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0


def test_only_symbol_scopes_the_cycle(tmp_path):
    cfg = _cfg(tmp_path, symbols=("BTC/USDT", "ETH/USDT")); cfg.auto_execute = True
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)),
                 only_symbol="ETH/USDT")
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT", "ETH/USDT"])
    assert st.positions["BTC/USDT"].qty == 0.0              # untouched
    assert st.positions["ETH/USDT"].qty > 0                 # only ETH processed


def test_stop_loss_still_executes_when_auto_off(tmp_path):
    cfg = _cfg(tmp_path); cfg.auto_execute = False          # auto OFF
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"]); st.cash = 0.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=210.0, stop_price=200.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0             # stop fired despite auto OFF — never deferred
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend


def test_live_auto_off_defers_no_real_order(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"; cfg.auto_execute = False
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                  # NO create_order when deferred
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert pend["BTC/USDT"]["action"] == "buy"


def test_shadow_auto_off_records_pending(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "shadow"; cfg.auto_execute = False
    class ShadowMarket:
        def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
        def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
        def fetch_price(self, ex, sym): return 159.0
        def fetch_balance(self, ex, symbols): return 5000.0, {s: 0.0 for s in symbols}
    bot.run_once(cfg, market=ShadowMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert pend["BTC/USDT"]["action"] == "buy"             # shadow proposes for the live-manual workflow


def test_status_carries_auto_execute(tmp_path):
    cfg = _cfg(tmp_path); cfg.auto_execute = True
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["auto_execute"] is True
```

Add this import near the other `from engine.state import ...` usages at the top of `tests/test_bot.py`:

```python
from engine.state import save_pending
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_bot.py -k "auto_off or auto_on or forced or only_symbol or stop_loss_still or shadow_auto or status_carries_auto" -v`
Expected: FAIL (TypeError on unexpected `only_symbol`/`forced_decision`, or assertion failures — deferral not implemented).

- [ ] **Step 3: Implement**

In `engine/bot.py`:

**(a)** Add `"auto_execute": cfg.auto_execute,` to `_status_payload` (right after the `"armed": _live_armed(),` line):

```python
        "armed": _live_armed(),
        "auto_execute": cfg.auto_execute,
        "interval_seconds": cfg.interval_seconds,
```

**(b)** Add the helper after `_live_armed` (before `_update_meta`):

```python
def _record_pending(pending: dict, sym: str, order, decision, price: float, ts: str) -> None:
    """Set or clear a deferred suggestion (auto-execute off). Actionable -> store; else drop."""
    if order is not None:
        pending[sym] = {"ts": ts, "action": order.side, "size": decision.size,
                        "reason": decision.reason, "price": price}
    else:
        pending.pop(sym, None)
```

**(c)** Change the `run_once` signature:

```python
def run_once(cfg=None, market=None, strategy=None, only_symbol=None, forced_decision=None) -> None:
```

**(d)** Pass the params through the live dispatch inside `run_once` (only the `_run_live` call changes):

```python
        if _live_armed():
            _run_live(cfg, market, strategy, only_symbol, forced_decision)
```

**(e)** In the paper branch, load pending right after `st = state_mod.load_state(...)`:

```python
        st = state_mod.load_state(cfg.data_dir, cfg.paper_capital, cfg.symbols)
        pending = state_mod.load_pending(cfg.data_dir)
```

**(f)** At the top of the paper `for sym in cfg.symbols:` loop body, add the scope skip (before the `try:`):

```python
        for sym in cfg.symbols:
            if only_symbol is not None and sym != only_symbol:
                continue
            try:
```

**(g)** Replace the paper decision block. Current:

```python
            reason = broker.force_close(pos, price, cfg.risk)
            if reason:                                # "liquidation" | "stop-loss"
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strategy(feats, pos, st.cash, cfg)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason
```

New:

```python
            reason = broker.force_close(pos, price, cfg.risk)
            if reason:                                # "liquidation" | "stop-loss" — ALWAYS executes
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = forced_decision if forced_decision is not None else strategy(feats, pos, st.cash, cfg)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason
                if forced_decision is None and not cfg.auto_execute:   # defer strategy decisions only
                    act = order.side if order else "hold"
                    state_mod.append_decision(
                        {"ts": ts, "symbol": sym, "action": act, "reason": reason,
                         "price": price, "executed": False}, cfg.data_dir)
                    _record_pending(pending, sym, order, decision, price, ts)
                    print(f"[{sym}] PENDING {act} @ {price:.2f} — {reason}")
                    continue
            pending.pop(sym, None)                     # executing/holding now — no stale suggestion
```

**(h)** In the paper branch, save pending before the status write. Current end of the `with` block:

```python
        try:                                     # advisory: a status write error never aborts the cycle
            state_mod.write_status(
                _status_payload(cfg, ts, st.funding_accrued, st.last_funding_ts), cfg.data_dir)
```

Insert above it:

```python
        state_mod.save_pending(pending, cfg.data_dir)
        try:                                     # advisory: a status write error never aborts the cycle
            state_mod.write_status(
                _status_payload(cfg, ts, st.funding_accrued, st.last_funding_ts), cfg.data_dir)
```

**(i)** In `_run_shadow`, load pending right after the balance fetch block (before `prices: dict[str, float] = {}`):

```python
        pending = state_mod.load_pending(cfg.data_dir)
        prices: dict[str, float] = {}
```

After the shadow `append_decision(...)` call and its `if order is None:/else` print block, add the pending record (inside the `for sym` loop, after the print lines):

```python
            if not cfg.auto_execute:
                _record_pending(pending, sym, order, decision, price, ts)
            else:
                pending.pop(sym, None)
```

And save pending before `_run_shadow`'s status write:

```python
        state_mod.save_pending(pending, cfg.data_dir)
        try:                                     # advisory; mode=shadow, no funding state in shadow
            state_mod.write_status(_status_payload(cfg, ts, 0.0, None), cfg.data_dir)
```

**(j)** Change the `_run_live` signature:

```python
def _run_live(cfg, market, strategy, only_symbol=None, forced_decision=None) -> None:
```

Load pending right after `meta = state_mod.load_live_meta(cfg.data_dir)`:

```python
        meta = state_mod.load_live_meta(cfg.data_dir)
        pending = state_mod.load_pending(cfg.data_dir)
```

Add the scope skip at the top of the `_run_live` `for sym in cfg.symbols:` loop body (before the `try:`):

```python
        for sym in cfg.symbols:
            if only_symbol is not None and sym != only_symbol:
                continue
            try:
```

Replace the `_run_live` decision block. Current:

```python
            reason = broker.force_close(pos, price, cfg.risk)   # spot -> only "stop-loss" can fire
            if reason:
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strategy(feats, pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
                reason = decision.reason
```

New:

```python
            reason = broker.force_close(pos, price, cfg.risk)   # spot -> only "stop-loss" can fire; ALWAYS executes
            if reason:
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = forced_decision if forced_decision is not None else strategy(feats, pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
                reason = decision.reason
                if forced_decision is None and not cfg.auto_execute:   # defer strategy decisions only
                    act = order.side if order else "hold"
                    state_mod.append_decision(
                        {"ts": ts, "symbol": sym, "action": act, "reason": reason,
                         "price": price, "executed": False}, cfg.data_dir)
                    _record_pending(pending, sym, order, decision, price, ts)
                    print(f"[LIVE][{sym}] PENDING {act} @ {price:.2f} — {reason}")
                    continue
            pending.pop(sym, None)                     # executing now — no stale suggestion
```

Save pending at the end of `_run_live`, right after `_write_live_mirror(...)`:

```python
        _write_live_mirror(cfg, ts, cash, qty_by, meta, prices)
        state_mod.save_pending(pending, cfg.data_dir)
        _safe_write_status(cfg, ts, halted=halted_mid)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_bot.py -v`
Expected: PASS (new tests + all pre-existing bot tests still green — the auto-on path is unchanged behavior).

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat(engine): defer strategy decisions to pending when auto_execute off (stop-loss always executes)"
```

---

### Task 4: Engine — `engine.execute` entry point

**Files:**
- Create: `engine/execute.py`
- Test: `tests/test_execute.py`

**Interfaces:**
- Consumes: `run_once(..., only_symbol, forced_decision)` (Task 3); `state_mod.load_pending` (Task 2); `_live_armed` (engine/bot.py).
- Produces: `engine.execute.main(symbol: str, cfg=None, market=None) -> int` (exit codes: 0 ok, 1 no arg, 2 shadow, 3 live-not-armed, 4 no pending); runnable as `python -m engine.execute SYMBOL`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_execute.py`:

```python
import json as _json
import pandas as pd
from engine import execute
from engine.config import Config, RiskConfig, LLMConfig, SentimentConfig
from engine.models import Decision, Fill
from engine.state import save_pending, load_state


# self-contained fakes (tests/ is not a package — do not import from test_bot)
def _cfg(tmp_path, symbols=("BTC/USDT",)):
    return Config(exchange="x", symbols=list(symbols), timeframe="15m",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True),
                  sentiment=SentimentConfig(enabled=False))


def _df():
    closes = [100.0 + i for i in range(60)]
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes,
                         "volume": [5.0] * 60})


class FakeMarket:
    def make_exchange(self, name): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
    def fetch_price(self, ex, sym): return 159.0


class _LiveMarket:
    """Fake live market; records create_order calls and returns a closed fill."""
    def __init__(self, cash=5000.0, qty=None, price=159.0):
        self.cash, self.qty, self.price = cash, qty or {}, price
        self.orders = []
    def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
    def fetch_price(self, ex, sym): return self.price
    def fetch_balance(self, ex, symbols): return self.cash, {s: self.qty.get(s, 0.0) for s in symbols}
    def clamp_to_market(self, ex, sym, qty, price): return qty
    def create_order(self, ex, sym, side, qty, ref_price, ts):
        self.orders.append((sym, side, qty))
        return Fill(sym, side, qty, ref_price, qty * ref_price * 0.001, ts)


def _strat(decision):
    return lambda features, position, cash, cfg: decision


def _seed_pending(tmp_path, sym="BTC/USDT", action="buy", size=1.0):
    save_pending({sym: {"ts": "t", "action": action, "size": size, "reason": "r", "price": 159.0}},
                 str(tmp_path))


def test_execute_paper_fills_and_clears_pending(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "paper"; cfg.auto_execute = False
    _seed_pending(tmp_path)
    # the stored buy is forced through run_once; the strategy (hybrid/LLM) is never called
    code = execute.main("BTC/USDT", cfg=cfg, market=FakeMarket())
    assert code == 0
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0                 # the stored buy executed
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend                           # cleared after execution


def test_execute_shadow_mode_refuses(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "shadow"
    _seed_pending(tmp_path)
    assert execute.main("BTC/USDT", cfg=cfg, market=FakeMarket()) == 2
    assert not (tmp_path / "trades.csv").exists()


def test_execute_live_unarmed_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ARMED", raising=False)
    cfg = _cfg(tmp_path); cfg.mode = "live"
    _seed_pending(tmp_path)
    assert execute.main("BTC/USDT", cfg=cfg, market=_LiveMarket()) == 3


def test_execute_no_pending_returns_4(tmp_path):
    cfg = _cfg(tmp_path); cfg.mode = "paper"
    assert execute.main("BTC/USDT", cfg=cfg, market=FakeMarket()) == 4


def test_execute_live_armed_places_real_order(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"; cfg.auto_execute = False
    _seed_pending(tmp_path)
    mk = _LiveMarket()
    code = execute.main("BTC/USDT", cfg=cfg, market=mk)
    assert code == 0
    assert len(mk.orders) == 1 and mk.orders[0][1] == "buy"  # a REAL order placed
    pend = _json.loads((tmp_path / "pending.json").read_text())
    assert "BTC/USDT" not in pend
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_execute.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.execute'`.

- [ ] **Step 3: Implement**

Create `engine/execute.py`:

```python
import logging
import sys

from engine import state as state_mod
from engine.bot import run_once, _live_armed
from engine.config import load_config
from engine.env import load_dotenv
from engine.models import Decision

log = logging.getLogger("execute")


def main(symbol: str, cfg=None, market=None) -> int:
    """Execute one stored pending suggestion for `symbol`. Returns a shell exit code."""
    if cfg is None:
        load_dotenv()                 # honor a .env arm before checking _live_armed()
        cfg = load_config()
    if cfg.mode == "shadow":
        print("[EXECUTE] shadow mode is dry-run; switch to paper or live to place orders")
        return 2
    if cfg.mode == "live" and not _live_armed():
        print("[EXECUTE] live mode but LIVE_TRADING_ARMED != 'yes' — relaunch the app armed to place real orders")
        return 3
    p = state_mod.load_pending(cfg.data_dir).get(symbol)
    if not p:
        print(f"[EXECUTE] no pending suggestion for {symbol}")
        return 4
    decision = Decision(action=p["action"], size=float(p.get("size", 1.0)), reason=p.get("reason", ""))
    run_once(cfg=cfg, market=market, only_symbol=symbol, forced_decision=decision)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("usage: python -m engine.execute SYMBOL")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_execute.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/execute.py tests/test_execute.py
git commit -m "feat(engine): engine.execute — run one stored suggestion (mode-guarded, forced decision)"
```

---

### Task 5: Lib — pending parse/remove + snapshot wiring

**Files:**
- Create: `desktop/src/lib/pending.ts` (`removePending`)
- Modify: `desktop/src/lib/parse.ts` (`Pending` type, `parsePending`, `Snapshot.pending`, `Status.auto_execute`)
- Modify: `desktop/src/lib/snapshot.ts` (read `pending.json`)
- Test: `desktop/src/lib/pending.test.ts`, `desktop/src/lib/snapshot.test.ts`

**Interfaces:**
- Produces: `Pending = Record<string, { ts: string; action: string; size: number; reason: string; price: number }>`; `parsePending(raw: unknown): Pending`; `removePending(dir: string, sym: string): Promise<Pending>`; `Snapshot.pending: Pending`; `Status.auto_execute?: boolean`.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/lib/pending.test.ts`:

```ts
import { test, expect } from "vitest";
import { parsePending, removePending } from "./pending";
import { mkdtempSync, writeFileSync, readFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

test("parsePending keeps valid entries and drops malformed", () => {
  const raw = {
    "BTC/USDT": { ts: "t", action: "buy", size: 0.5, reason: "r", price: 100 },
    "BAD/ONE": { size: 1 },        // no action -> dropped
    "BAD/TWO": "nope",             // not an object -> dropped
  };
  const out = parsePending(raw);
  expect(Object.keys(out)).toEqual(["BTC/USDT"]);
  expect(out["BTC/USDT"].action).toBe("buy");
});

test("parsePending returns {} for non-objects", () => {
  expect(parsePending([1, 2])).toEqual({});
  expect(parsePending(null)).toEqual({});
  expect(parsePending("x")).toEqual({});
});

test("removePending removes one key, preserves others", async () => {
  const d = mkdtempSync(join(tmpdir(), "pend-"));
  writeFileSync(join(d, "pending.json"), JSON.stringify({
    "BTC/USDT": { ts: "t", action: "buy", size: 1, reason: "r", price: 1 },
    "ETH/USDT": { ts: "t", action: "sell", size: 1, reason: "r", price: 2 },
  }));
  const left = await removePending(d, "BTC/USDT");
  expect(Object.keys(left)).toEqual(["ETH/USDT"]);
  expect(Object.keys(JSON.parse(readFileSync(join(d, "pending.json"), "utf8")))).toEqual(["ETH/USDT"]);
});

test("removePending on a missing file is a no-op {}", async () => {
  const d = mkdtempSync(join(tmpdir(), "pend-"));
  expect(await removePending(d, "BTC/USDT")).toEqual({});
});
```

Add to `desktop/src/lib/snapshot.test.ts` (read the existing file first; append a test that a written `pending.json` is parsed into `snap.pending`). If no snapshot.test.ts test covers a tmp dir yet, use this self-contained test:

```ts
import { test, expect } from "vitest";
import { readSnapshot } from "./snapshot";
import { mkdtempSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

test("readSnapshot parses pending.json into snap.pending", async () => {
  const d = mkdtempSync(join(tmpdir(), "snap-"));
  writeFileSync(join(d, "pending.json"), JSON.stringify({
    "ETH/USDT": { ts: "t", action: "sell", size: 1, reason: "r", price: 1583.35 },
  }));
  const snap = await readSnapshot(d);
  expect(snap.pending["ETH/USDT"].action).toBe("sell");
});

test("readSnapshot pending defaults to {} when absent", async () => {
  const d = mkdtempSync(join(tmpdir(), "snap-"));
  const snap = await readSnapshot(d);
  expect(snap.pending).toEqual({});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd desktop && npx vitest run src/lib/pending.test.ts src/lib/snapshot.test.ts`
Expected: FAIL (`Cannot find module './pending'`; `snap.pending` undefined).

- [ ] **Step 3: Implement**

In `desktop/src/lib/parse.ts`, add the type (after the `Decision` type) :

```ts
export type Pending = Record<string, { ts: string; action: string; size: number; reason: string; price: number }>;
```

Add `auto_execute?: boolean` to the `Status` type (extend the existing `armed?: boolean` line group):

```ts
export type Status = { ts: string; strategy: string; exchange: string; mode?: string; halted?: boolean; armed?: boolean;
                       auto_execute?: boolean;
                       interval_seconds?: number; symbols?: string[]; risk: RiskStatus; funding: FundingStatus };
```

Add `pending: Pending` to the `Snapshot` type:

```ts
export type Snapshot = { state: State | null; trades: Trade[]; decisions: Decision[];
                         sentiment: SentimentSnapshot | null;
                         status: Status | null; backtest: BacktestPoint[]; pending: Pending };
```

Add the parser (alongside the other `parse*` functions):

```ts
export function parsePending(raw: unknown): Pending {
  const out: Pending = {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return out;
  for (const [sym, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!v || typeof v !== "object") continue;
    const e = v as Record<string, unknown>;
    if (typeof e.action !== "string") continue;
    out[sym] = {
      ts: typeof e.ts === "string" ? e.ts : "",
      action: e.action,
      size: Number(e.size) || 0,
      reason: typeof e.reason === "string" ? e.reason : "",
      price: Number(e.price) || 0,
    };
  }
  return out;
}
```

Create `desktop/src/lib/pending.ts` (fs via lazy dynamic `import()` so the renderer build stays clean, like `symbols.ts`):

```ts
import { parsePending, type Pending } from "./parse";

export { parsePending };
export type { Pending };

export async function removePending(dir: string, sym: string): Promise<Pending> {
  const { readFile, writeFile, mkdir } = await import("fs/promises");
  const { join } = await import("path");
  let current: Pending = {};
  try {
    current = parsePending(JSON.parse(await readFile(join(dir, "pending.json"), "utf8")));
  } catch {
    current = {};                 // missing/corrupt -> nothing to remove
  }
  delete current[sym];
  await mkdir(dir, { recursive: true });
  await writeFile(join(dir, "pending.json"), JSON.stringify(current), "utf8");
  return current;
}
```

In `desktop/src/lib/snapshot.ts`, import `parsePending` + `Pending` from `./parse` and read the file:

```ts
import { parseTradesCsv, parseDecisions, parseSentiment, parseBacktestCsv, parsePending, Snapshot, State, SentimentSnapshot, Status, BacktestPoint, Pending } from "./parse";
```

In `readSnapshot`, add before the `return`:

```ts
  const pending = await readOr<Pending>(join(dir, "pending.json"), {}, (s) => parsePending(JSON.parse(s)));
  return { state, trades, decisions, sentiment, status, backtest, pending };
```

Because `Snapshot.pending` is now required, update the one other `Snapshot` literal — `EMPTY` in `desktop/src/renderer/src/App.tsx` — so the build stays valid (Task 7 runs `npm run build`):

```tsx
const EMPTY: Snapshot = { state: null, trades: [], decisions: [], sentiment: null, status: null, backtest: [], pending: {} };
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd desktop && npx vitest run src/lib/pending.test.ts src/lib/snapshot.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/pending.ts desktop/src/lib/parse.ts desktop/src/lib/snapshot.ts desktop/src/renderer/src/App.tsx desktop/src/lib/pending.test.ts desktop/src/lib/snapshot.test.ts
git commit -m "feat(dashboard): pending parse/remove + snapshot wiring + auto_execute on Status"
```

---

### Task 6: Lib — control.json merge writers

**Files:**
- Modify: `desktop/src/lib/control.ts` (merge `_merge`; `writeControl` preserves `auto_execute`; new `writeAutoExecute`)
- Test: `desktop/src/lib/control.test.ts`

**Interfaces:**
- Produces: `writeControl(dir: string, mode: string): Promise<void>` (merges, validates mode); `writeAutoExecute(dir: string, on: boolean): Promise<void>` (merges).

- [ ] **Step 1: Write the failing tests**

Add to `desktop/src/lib/control.test.ts`:

```ts
import { writeAutoExecute } from "./control";

test("writeControl preserves an existing auto_execute", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeAutoExecute(d, true);
  await writeControl(d, "live");
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ auto_execute: true, mode: "live" });
});

test("writeAutoExecute preserves an existing mode", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeControl(d, "shadow");
  await writeAutoExecute(d, true);
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ mode: "shadow", auto_execute: true });
});

test("writeAutoExecute false round-trips", async () => {
  const d = mkdtempSync(join(tmpdir(), "ctrl-"));
  await writeAutoExecute(d, false);
  expect(JSON.parse(readFileSync(join(d, "control.json"), "utf8"))).toEqual({ auto_execute: false });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd desktop && npx vitest run src/lib/control.test.ts`
Expected: FAIL (`writeAutoExecute` not exported; preservation tests fail against the clobbering writer).

- [ ] **Step 3: Implement**

Replace `desktop/src/lib/control.ts` with:

```ts
import { writeFile, mkdir, readFile } from "fs/promises";
import { join } from "path";

const VALID = new Set(["paper", "shadow", "live"]);

async function _merge(dir: string, patch: Record<string, unknown>): Promise<void> {
  await mkdir(dir, { recursive: true });
  let current: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(await readFile(join(dir, "control.json"), "utf8"));
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) current = parsed;
  } catch {
    current = {};                 // missing/corrupt -> start clean
  }
  await writeFile(join(dir, "control.json"), JSON.stringify({ ...current, ...patch }), "utf8");
}

export async function writeControl(dir: string, mode: string): Promise<void> {
  if (!VALID.has(mode)) throw new Error(`invalid mode: ${mode}`);
  await _merge(dir, { mode });
}

export async function writeAutoExecute(dir: string, on: boolean): Promise<void> {
  await _merge(dir, { auto_execute: on });
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd desktop && npx vitest run src/lib/control.test.ts`
Expected: PASS (including the 3 pre-existing `writeControl` tests — a merge into an empty file still yields `{ mode }`).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/control.ts desktop/src/lib/control.test.ts
git commit -m "feat(dashboard): control.json merge writers (writeControl + writeAutoExecute)"
```

---

### Task 7: Main — armed spawn + IPC + preload (the live-order carve-out)

**Files:**
- Modify: `desktop/src/main/engine.ts` (`runEngine` shared body; `spawnEngine` pinned; `spawnEngineArmed` un-pinned; `executeSuggestion`)
- Modify: `desktop/src/main/index.ts` (3 IPC handlers)
- Modify: `desktop/src/preload/index.ts` (3 api methods)
- Modify: `desktop/vitest.config.ts` (include `src/main/`)
- Test: `desktop/src/main/engine.test.ts` (keystone carve-out test)

**Interfaces:**
- Consumes: `executeSuggestion` → `engine.execute` (Task 4); `removePending` (Task 5); `writeAutoExecute` (Task 6).
- Produces: `executeSuggestion(symbol: string): Promise<RunResult>` (un-pinned); IPC channels `execute-suggestion`, `dismiss-suggestion`, `set-auto-execute`; preload `executeSuggestion`/`dismissSuggestion`/`setAutoExecute`.

- [ ] **Step 1: Write the failing test**

First widen the vitest glob in `desktop/vitest.config.ts`:

```ts
  test: { include: ["src/lib/**/*.test.ts", "src/main/**/*.test.ts"], environment: "node" },
```

Create `desktop/src/main/engine.test.ts`:

```ts
import { vi, test, expect, beforeEach } from "vitest";

const spawnMock = vi.fn();
vi.mock("child_process", () => ({ spawn: (...a: unknown[]) => spawnMock(...a) }));

import { runBot, executeSuggestion } from "./engine";

function fakeChild() {
  return {
    stderr: { on: () => {} },
    on: (e: string, cb: (c: number) => void) => { if (e === "close") cb(0); },
  };
}

beforeEach(() => { spawnMock.mockReset(); spawnMock.mockReturnValue(fakeChild()); });

test("executeSuggestion inherits the real LIVE_TRADING_ARMED (NOT pinned to 'no')", async () => {
  process.env.LIVE_TRADING_ARMED = "yes";
  await executeSuggestion("ETH/USDT");
  const opts = spawnMock.mock.calls[0][2] as { env: NodeJS.ProcessEnv };
  expect(opts.env.LIVE_TRADING_ARMED).toBe("yes");           // armed click can place a real order
  expect(spawnMock.mock.calls[0][1]).toContain("engine.execute");
});

test("runBot pins LIVE_TRADING_ARMED to 'no' regardless of the real env", async () => {
  process.env.LIVE_TRADING_ARMED = "yes";
  await runBot();
  const opts = spawnMock.mock.calls[0][2] as { env: NodeJS.ProcessEnv };
  expect(opts.env.LIVE_TRADING_ARMED).toBe("no");            // scheduler/Run-now can never auto-fire live
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd desktop && npx vitest run src/main/engine.test.ts`
Expected: FAIL (`executeSuggestion` not exported).

- [ ] **Step 3: Implement**

In `desktop/src/main/engine.ts`, replace `spawnEngine` with a shared `runEngine` + two spawn wrappers, and add `executeSuggestion`:

```ts
function runEngine(args: string[], env: NodeJS.ProcessEnv): Promise<RunResult> {
  const repoRoot = resolve(dataDir(), "..");
  return new Promise((resolveP) => {
    const child = spawn(pythonPath(repoRoot), args, { cwd: repoRoot, env });
    let stderr = "";
    child.stderr.on("data", (d) => { stderr = (stderr + d.toString()).slice(-2048); });
    child.on("error", (e) => resolveP({ ok: false, code: null, stderrTail: e.message }));
    child.on("close", (code) => resolveP({ ok: code === 0, code, stderrTail: stderr.trim() }));
  });
}

// Pinned: the scheduler, Run-now, and backtest can NEVER carry a live-trading arm.
function spawnEngine(args: string[]): Promise<RunResult> {
  return runEngine(args, pinnedEnv(process.env));
}

// The ONE un-pinned engine spawn. Manual Execute inherits the operator's real
// LIVE_TRADING_ARMED so a confirmed click can place a real order in live mode.
// Reachable ONLY from the execute-suggestion IPC. The engine still enforces the
// two-switch (mode:live + LIVE_TRADING_ARMED=yes + no data/HALT); an unarmed app fails closed.
function spawnEngineArmed(args: string[]): Promise<RunResult> {
  return runEngine(args, process.env);
}
```

Keep `runBacktest` and `runBot` calling `spawnEngine` (unchanged). Add at the bottom:

```ts
export function executeSuggestion(symbol: string): Promise<RunResult> {
  return spawnEngineArmed(["-m", "engine.execute", symbol]);
}
```

In `desktop/src/main/index.ts`, extend imports and register the handlers:

```ts
import { runBacktest, runBot, executeSuggestion } from "./engine";
import { writeControl, writeAutoExecute } from "../lib/control";
import { removePending } from "../lib/pending";
```

Inside `app.whenReady().then(() => { ... })`, alongside the existing `ipcMain.handle` calls:

```ts
    ipcMain.handle("execute-suggestion", (_e, sym: string) => executeSuggestion(sym));
    ipcMain.handle("dismiss-suggestion", (_e, sym: string) => removePending(dataDir(), sym));
    ipcMain.handle("set-auto-execute", (_e, on: boolean) => writeAutoExecute(dataDir(), on));
```

In `desktop/src/preload/index.ts`, add to the `api` object:

```ts
  executeSuggestion: (symbol: string) => ipcRenderer.invoke("execute-suggestion", symbol),
  dismissSuggestion: (symbol: string) => ipcRenderer.invoke("dismiss-suggestion", symbol),
  setAutoExecute: (on: boolean) => ipcRenderer.invoke("set-auto-execute", on),
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd desktop && npx vitest run src/main/engine.test.ts && npm run build`
Expected: both PASS / build exit 0.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/engine.ts desktop/src/main/index.ts desktop/src/preload/index.ts desktop/vitest.config.ts desktop/src/main/engine.test.ts
git commit -m "feat(dashboard): un-pinned executeSuggestion spawn + execute/dismiss/auto-execute IPC (carve-out tested)"
```

---

### Task 8: UI — Settings auto-execute toggle

**Files:**
- Modify: `desktop/src/renderer/src/components/Settings.tsx`
- Verify: Playwright CLI

**Interfaces:**
- Consumes: `status.auto_execute` (Task 5); preload `setAutoExecute` (Task 7).

- [ ] **Step 1: Implement the toggle**

In `Settings.tsx`, add `setAutoExecute` to the `api` type block:

```ts
    setAutoExecute: (on: boolean) => Promise<void>;
```

Add state + seed-from-status + handler (near the other hooks):

```tsx
  const [autoExec, setAutoExec] = useState(false);
  const [autoSeeded, setAutoSeeded] = useState(false);

  useEffect(() => {
    if (!autoSeeded && status && typeof status.auto_execute === "boolean") {
      setAutoExec(status.auto_execute); setAutoSeeded(true);
    }
  }, [status, autoSeeded]);

  const toggleAuto = async (on: boolean): Promise<void> => {
    setAutoExec(on);
    try { await api.setAutoExecute(on); } catch { /* status poll reconciles on failure */ }
  };
```

Render the toggle as the first control in the returned form (above the Trading-pairs section label):

```tsx
      <label className="settings-row">
        <input type="checkbox" checked={autoExec} onChange={(e) => toggleAuto(e.target.checked)} />
        Auto-execute trades — when off, the bot only proposes; you Execute/Dismiss each suggestion. In live mode an Execute places a real order.
      </label>
```

- [ ] **Step 2: Build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 3: Playwright verify (1280 / 768 / 375)**

Serve `desktop/out/renderer` and stub `window.api` before the bundle loads (CommonJS Playwright import from the myhermes node_modules, per the project's established harness). Write a script under the scratchpad that:
- stubs `window.api.getSnapshot` to return a snapshot whose `status.auto_execute === true` and `pending === {}`;
- stubs `window.api.setAutoExecute` to record calls;
- navigates to Settings, asserts the checkbox is **checked** (reflects `status.auto_execute`);
- clicks it, asserts `setAutoExecute(false)` was called;
- screenshots at 1280 / 768 / 375.

Expected: checkbox reflects the stub, toggling calls `setAutoExecute`, screenshots clean at all three widths.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/src/components/Settings.tsx
git commit -m "feat(dashboard): Settings auto-execute toggle (reflects status, writes control.json)"
```

---

### Task 9: UI — Pending suggestions panel on Overview

**Files:**
- Create: `desktop/src/renderer/src/components/PendingPanel.tsx`
- Modify: `desktop/src/renderer/src/App.tsx` (render in `Overview`; add `pending: {}` to `EMPTY`)
- Modify: the renderer stylesheet that defines `.bt-run` / `.card` (add the panel CSS)
- Verify: Playwright CLI

**Interfaces:**
- Consumes: `snap.pending` (Task 5), `snap.status` (mode); preload `executeSuggestion` / `dismissSuggestion` (Task 7).

- [ ] **Step 1: Create the panel**

Create `desktop/src/renderer/src/components/PendingPanel.tsx`:

```tsx
import { useState } from "react";
import type { Pending, Status } from "../../../lib/parse";

const api = (window as unknown as {
  api: {
    executeSuggestion: (s: string) => Promise<{ ok: boolean; stderrTail: string }>;
    dismissSuggestion: (s: string) => Promise<unknown>;
  };
}).api;

function ago(ts: string, now: number): string {
  const ms = now - new Date(ts).getTime();
  if (!isFinite(ms) || ms < 60000) return "just now";
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

export default function PendingPanel({ pending, status }: { pending: Pending; status: Status | null }): React.JSX.Element | null {
  const syms = Object.keys(pending);
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState<{ sym: string; text: string; err: boolean } | null>(null);
  if (!syms.length) return null;
  const isLive = status?.mode === "live";

  const execute = async (sym: string): Promise<void> => {
    const p = pending[sym];
    if (isLive && !window.confirm(`Place a REAL market ${p.action.toUpperCase()} of ${sym}? This uses real funds.`)) return;
    setBusy(sym); setMsg(null);
    try {
      const r = await api.executeSuggestion(sym);
      setMsg({ sym, text: r.ok ? "Executed — updating…" : (r.stderrTail || "Execute failed"), err: !r.ok });
    } catch (e) {
      setMsg({ sym, text: String(e), err: true });
    } finally {
      setBusy("");
    }
  };

  const dismiss = async (sym: string): Promise<void> => {
    setBusy(sym);
    try { await api.dismissSuggestion(sym); } finally { setBusy(""); }
  };

  return (
    <section className="card pending-panel">
      <h2>Pending suggestions <span className="muted">— approve to trade</span></h2>
      {syms.map((sym) => {
        const p = pending[sym];
        return (
          <div className="pending-row" key={sym}>
            <span className="pending-sym">{sym}</span>
            <span className={`pending-side ${p.action}`}>{p.action.toUpperCase()}</span>
            <span className="pending-reason">{p.reason}</span>
            <span className="muted">{ago(p.ts, Date.now())} · @ ${p.price.toFixed(2)}</span>
            <button className="bt-run" disabled={busy === sym} onClick={() => execute(sym)}>
              {isLive ? "Execute (LIVE)" : "Execute"}
            </button>
            <button className="bt-ghost" disabled={busy === sym} onClick={() => dismiss(sym)}>Dismiss</button>
            {msg && msg.sym === sym && <span className={msg.err ? "bt-error" : "muted"}>{msg.text}</span>}
          </div>
        );
      })}
    </section>
  );
}
```

- [ ] **Step 2: Wire into Overview**

In `desktop/src/renderer/src/App.tsx`, import the panel (`EMPTY` already carries `pending: {}` from Task 5):

```tsx
import PendingPanel from "./components/PendingPanel";
```

In the `Overview` function, render the panel first (returns null when empty, so it only shows in manual mode with suggestions):

```tsx
  return (
    <>
      <PendingPanel pending={snap.pending} status={snap.status} />
      <div className="kpi-row">
```

- [ ] **Step 3: Add CSS**

Append to `desktop/src/renderer/src/index.css` (the renderer stylesheet that defines `.card`, `.bt-run`, `.muted`):

```css
.pending-panel { border-left: 3px solid var(--accent, #4f8cff); }
.pending-row { display: flex; align-items: center; gap: 12px; padding: 8px 0; flex-wrap: wrap; }
.pending-sym { font-weight: 600; min-width: 92px; }
.pending-side { font-weight: 700; padding: 2px 8px; border-radius: 6px; font-size: 12px; }
.pending-side.buy { color: var(--up, #2ecc71); background: rgba(46, 204, 113, 0.12); }
.pending-side.sell { color: var(--down, #e74c3c); background: rgba(231, 76, 60, 0.12); }
.pending-reason { flex: 1; color: var(--muted, #8a93a6); font-size: 13px; }
.bt-ghost { background: transparent; border: 1px solid var(--border, #2a3346); color: var(--muted, #8a93a6);
            border-radius: 8px; padding: 6px 12px; cursor: pointer; }
.bt-ghost:disabled { opacity: 0.5; cursor: default; }
```

- [ ] **Step 4: Build**

Run: `cd desktop && npm run build`
Expected: exit 0.

- [ ] **Step 5: Playwright verify (1280 / 768 / 375)**

Write a scratchpad script that stubs `window.api` and:
- with `snap.pending = { "ETH/USDT": { ts: <2h ago>, action: "sell", size: 1, reason: "took profit", price: 1583.35 } }` and `status.mode = "paper"`: asserts the panel renders the ETH row with a **Execute** button; clicking it calls `executeSuggestion("ETH/USDT")` (no confirm in paper);
- with `status.mode = "live"`: clicking **Execute (LIVE)** triggers a `confirm` dialog (accept it via Playwright's dialog handler) and then calls `executeSuggestion`;
- clicking **Dismiss** calls `dismissSuggestion("ETH/USDT")`;
- with `snap.pending = {}`: asserts the panel is absent (no `.pending-panel`);
- screenshots at 1280 / 768 / 375.

Expected: all assertions pass; the panel is hidden when empty; the live path confirms; screenshots clean.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/src/components/PendingPanel.tsx desktop/src/renderer/src/App.tsx desktop/src/renderer/src/*.css
git commit -m "feat(dashboard): Pending suggestions panel on Overview (Execute/Dismiss, live confirm)"
```

---

## Final verification (after all tasks)

- [ ] Engine suite green: `python -m pytest -q`
- [ ] Desktop unit suite green: `cd desktop && npx vitest run`
- [ ] Build clean: `cd desktop && npm run build` (exit 0)
- [ ] **Safety grep:** `grep -rn "create_order" engine/` shows only the def (market.py), the ccxt call, the log line, and the single `_run_live` caller — manual execute reaches it through `_run_live`, not a second site. `grep -rn "cancel_order\|withdraw" engine/` = 0.
- [ ] **Carve-out grep:** `grep -rn "spawnEngineArmed\|process.env" desktop/src/main/engine.ts` — `spawnEngineArmed` is used only by `executeSuggestion`; every other engine entry uses `spawnEngine` (pinned).
- [ ] Whole-branch review (Opus) per subagent-driven-development, with extra scrutiny on the live-order carve-out and the force_close-never-defers rule.
