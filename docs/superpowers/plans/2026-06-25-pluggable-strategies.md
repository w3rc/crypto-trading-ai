# Pluggable Strategies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot's decision brain selectable by config, and ship a deterministic indicator-rule strategy alongside the existing LLM hybrid.

**Architecture:** A strategy is a plain callable `(features, position, cash, cfg) -> Decision`, looked up by name in a `STRATEGIES` dict in `engine/strategies.py`. `bot.run_once` resolves the strategy once (fail-fast on a bad name) and dispatches to it where it currently calls `llm.decide`. The authoritative risk gate (`broker.plan_order`) and fill simulation are untouched.

**Tech Stack:** Python 3.14, pydantic (`Decision`), pyyaml (config), pytest. No new dependencies.

## Global Constraints

- **No new dependencies.** Stdlib + what's already imported only.
- **Default `strategy: hybrid` keeps live behavior byte-for-byte unchanged** — the running bot must be unaffected until the operator opts into another strategy.
- **New `Config` fields carry defaults** so the whole test suite stays green after every task.
- `broker.plan_order` stays the authoritative risk gate — strategies cannot bypass position caps or cash.
- Fail-safe HOLD: `hybrid` keeps `llm.decide`'s try/except; `indicator_rule` is pure arithmetic over a valid feature dict.
- Feature dict keys (from `indicators.compute_indicators` + bot): `price, rsi, macd, macd_signal, ma_fast, ma_slow, atr`.
- Spot, long-only. A `sell` while flat is a no-op at the gate; strategies do not duplicate that guard.
- Local commits OK (already authorized for this project). Do **not** push or open a PR without explicit go-ahead.

---

### Task 1: Config — `strategy` field + `RulesConfig`

**Files:**
- Modify: `engine/config.py`
- Modify: `engine/config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `RulesConfig(rsi_buy: float, rsi_sell: float, buy_size: float)` dataclass; `Config.strategy: str` (default `"hybrid"`); `Config.rules: RulesConfig` (default `RulesConfig()`). Consumed by Tasks 3 and 4.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_strategy_and_rules_load(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg = load_config("engine/config.yaml")
    assert cfg.strategy == "hybrid"
    assert cfg.rules.rsi_buy == 30
    assert cfg.rules.rsi_sell == 70
    assert cfg.rules.buy_size == 0.5

def test_strategy_and_rules_default_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.strategy == "hybrid"     # default when key absent
    assert cfg.rules.rsi_buy == 30      # default rules when block absent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'strategy'`

- [ ] **Step 3: Implement the config changes**

In `engine/config.py`, change the dataclasses import line:

```python
from dataclasses import dataclass, field
```

Add a `RulesConfig` dataclass (next to `RiskConfig`):

```python
@dataclass
class RulesConfig:
    rsi_buy: float = 30.0
    rsi_sell: float = 70.0
    buy_size: float = 0.5
```

Add two fields at the **end** of the `Config` dataclass (they have defaults, so they must come last):

```python
    strategy: str = "hybrid"
    rules: RulesConfig = field(default_factory=RulesConfig)
```

In `load_config`, just before the `return Config(`, read the rules block:

```python
    rules_raw = raw.get("rules", {})
```

Add these two arguments to the `Config(...)` call (after `llm=...`):

```python
        strategy=raw.get("strategy", "hybrid"),
        rules=RulesConfig(
            rsi_buy=float(rules_raw.get("rsi_buy", 30)),
            rsi_sell=float(rules_raw.get("rsi_sell", 70)),
            buy_size=float(rules_raw.get("buy_size", 0.5)),
        ),
```

In `engine/config.yaml`, add at the top level (after the `slippage_pct` line is fine; placement doesn't matter):

```yaml
strategy: hybrid
rules:
  rsi_buy: 30
  rsi_sell: 70
  buy_size: 0.5
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all, including the two pre-existing tests)

- [ ] **Step 5: Run the full suite (must stay green)**

Run: `python -m pytest -q`
Expected: PASS — existing `test_bot.py` still constructs `Config(...)` without the new fields and relies on their defaults.

- [ ] **Step 6: Commit**

```bash
git add engine/config.py engine/config.yaml tests/test_config.py
git commit -m "feat(config): strategy selector + RulesConfig (default hybrid)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Strategy seam — `engine/strategies.py`

**Files:**
- Create: `engine/strategies.py`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `engine.llm.decide(features, position, cash, llm_cfg) -> Decision`; `cfg.llm` from `Config`.
- Produces: `hybrid(features, position, cash, cfg) -> Decision`; `STRATEGIES: dict[str, callable]`; `get(name) -> callable` (raises `ValueError` listing valid names on miss). Consumed by Tasks 3 and 4.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_strategies.py`:

```python
import pytest
from types import SimpleNamespace
from engine import strategies
from engine.models import Decision, Position


def test_get_returns_registered_callable():
    assert strategies.get("hybrid") is strategies.hybrid


def test_get_unknown_name_raises_listing_valid():
    with pytest.raises(ValueError) as e:
        strategies.get("nope")
    assert "hybrid" in str(e.value)


def test_hybrid_delegates_to_llm_with_llm_cfg(monkeypatch):
    captured = {}

    def fake_decide(features, position, cash, llm_cfg):
        captured["call"] = (features, position, cash, llm_cfg)
        return Decision(action="hold", reason="stub")

    monkeypatch.setattr(strategies.llm, "decide", fake_decide)
    cfg = SimpleNamespace(llm="LLM_CFG")
    d = strategies.hybrid({"price": 1.0}, Position("BTC/USDT"), 100.0, cfg)
    assert d.reason == "stub"
    assert captured["call"][3] == "LLM_CFG"   # forwards cfg.llm, not the whole cfg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.strategies'`

- [ ] **Step 3: Create the module**

Create `engine/strategies.py`:

```python
from engine import llm
from engine.models import Decision


def hybrid(features, position, cash, cfg) -> Decision:
    """Indicators + LLM judgment — the v1 behavior, unchanged."""
    return llm.decide(features, position, cash, cfg.llm)


STRATEGIES = {"hybrid": hybrid}


def get(name):
    if name not in STRATEGIES:
        raise ValueError(f"unknown strategy {name!r}; choose from {sorted(STRATEGIES)}")
    return STRATEGIES[name]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/strategies.py tests/test_strategies.py
git commit -m "feat(strategies): strategy seam — registry, get(), hybrid

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Deterministic `indicator_rule` strategy

**Files:**
- Modify: `engine/strategies.py`
- Test: `tests/test_strategies.py`

**Interfaces:**
- Consumes: `cfg.rules` (`RulesConfig` from Task 1); feature keys `rsi, macd, macd_signal, ma_fast, ma_slow`.
- Produces: `indicator_rule(features, position, cash, cfg) -> Decision`, registered under `"indicator_rule"` in `STRATEGIES`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_strategies.py`:

```python
def _ns(rsi_buy=30, rsi_sell=70, buy_size=0.5):
    return SimpleNamespace(rules=SimpleNamespace(
        rsi_buy=rsi_buy, rsi_sell=rsi_sell, buy_size=buy_size))


_FLAT = Position("BTC/USDT")


def _feats(rsi, macd=0.0, sig=0.0, fast=100.0, slow=100.0):
    return {"price": 100.0, "rsi": rsi, "macd": macd, "macd_signal": sig,
            "ma_fast": fast, "ma_slow": slow, "atr": 1.0}


def test_oversold_is_buy_with_buy_size():
    d = strategies.indicator_rule(_feats(rsi=25), _FLAT, 1000.0, _ns(buy_size=0.4))
    assert d.action == "buy" and d.size == 0.4


def test_overbought_is_sell_full():
    d = strategies.indicator_rule(_feats(rsi=80), _FLAT, 1000.0, _ns())
    assert d.action == "sell" and d.size == 1.0


def test_neutral_is_hold():
    d = strategies.indicator_rule(_feats(rsi=50), _FLAT, 1000.0, _ns())
    assert d.action == "hold"


def test_conflicting_signals_is_hold():
    # bullish via rsi<30 AND bearish via macd<signal & fast<slow -> hold
    d = strategies.indicator_rule(
        _feats(rsi=25, macd=-1, sig=0, fast=99, slow=100), _FLAT, 1000.0, _ns())
    assert d.action == "hold"


def test_indicator_rule_registered():
    assert strategies.get("indicator_rule") is strategies.indicator_rule
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: FAIL — `AttributeError: module 'engine.strategies' has no attribute 'indicator_rule'`

- [ ] **Step 3: Add the strategy and register it**

In `engine/strategies.py`, add the function (after `hybrid`):

```python
def indicator_rule(features, position, cash, cfg) -> Decision:
    """Deterministic RSI/MACD/MA crossover rules. Long-only, no LLM."""
    r = cfg.rules
    rsi = features["rsi"]
    bullish = rsi < r.rsi_buy or (
        features["macd"] > features["macd_signal"]
        and features["ma_fast"] > features["ma_slow"])
    bearish = rsi > r.rsi_sell or (
        features["macd"] < features["macd_signal"]
        and features["ma_fast"] < features["ma_slow"])
    if bullish and not bearish:
        return Decision(action="buy", size=r.buy_size, reason=f"rule:bullish rsi={rsi:.0f}")
    if bearish and not bullish:
        return Decision(action="sell", size=1.0, reason=f"rule:bearish rsi={rsi:.0f}")
    return Decision(action="hold", reason=f"rule:neutral rsi={rsi:.0f}")
```

Change the registry line to include it:

```python
STRATEGIES = {"hybrid": hybrid, "indicator_rule": indicator_rule}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strategies.py -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Commit**

```bash
git add engine/strategies.py tests/test_strategies.py
git commit -m "feat(strategies): deterministic indicator_rule strategy

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire the seam into the bot loop

**Files:**
- Modify: `engine/bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `engine.strategies.get(name)`; `cfg.strategy`.
- Produces: `run_once(cfg=None, market=None, strategy=None)` — `strategy` is an injectable callable `(features, position, cash, cfg) -> Decision`; when `None`, resolved from `cfg.strategy`. (Replaces the old `llm=` injection param.)

- [ ] **Step 1: Update the bot tests to inject a fake strategy**

In `tests/test_bot.py`, delete the `FakeLLM` class:

```python
class FakeLLM:
    def __init__(self, decision): self.decision = decision
    def decide(self, features, position, cash, cfg, client=None): return self.decision
```

Replace it with a fake-strategy helper:

```python
def _strat(decision):
    return lambda features, position, cash, cfg: decision
```

Then replace every `llm=FakeLLM(` with `strategy=_strat(` in this file. There are 7 occurrences, e.g.:

```python
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
```
```python
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold")))
```
```python
    bot.run_once(cfg, market=market, strategy=_strat(Decision(action="buy", size=1.0)))
```
```python
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
```
```python
    bot.run_once(cfg, market=FakeMarket(price=0.0), strategy=_strat(Decision(action="hold")))
```
```python
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
```
```python
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="hold", reason="flat")))
```

(`_cfg` is unchanged — `Config` supplies the new `strategy`/`rules` defaults.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bot.py -v`
Expected: FAIL — `TypeError: run_once() got an unexpected keyword argument 'strategy'`

- [ ] **Step 3: Wire the strategy into `bot.py`**

Change the engine import line:

```python
from engine import broker, indicators, market as market_mod, strategies as strategies_mod, state as state_mod
```

Change the signature and resolution at the top of `run_once`:

```python
def run_once(cfg=None, market=None, strategy=None) -> None:
    cfg = cfg or load_config()
    market = market or market_mod
    strategy = strategy or strategies_mod.get(cfg.strategy)
```

Change the dispatch in the `else` branch (where the stop didn't trigger):

```python
            else:
                decision = strategy(feats, pos, st.cash, cfg)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason
```

(The old `llm = llm_mod` line and the `llm.decide(...)` call are removed by these edits. `llm as llm_mod` is no longer imported.)

- [ ] **Step 4: Run the bot tests to verify they pass**

Run: `python -m pytest tests/test_bot.py -v`
Expected: PASS — the loop now dispatches through the injected fake strategy.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all ~52 tests across config/strategies/bot/llm/broker/state/indicators).

- [ ] **Step 6: Smoke-check a real dispatch (no network)**

Run:
```bash
python -c "from engine import strategies; from engine.config import RulesConfig; from types import SimpleNamespace; \
f={'price':1,'rsi':20,'macd':1,'macd_signal':0,'ma_fast':2,'ma_slow':1,'atr':1}; \
print(strategies.get('indicator_rule')(f, None, 0, SimpleNamespace(rules=RulesConfig())))"
```
Expected: a `Decision` with `action='buy'`.

- [ ] **Step 7: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat(bot): dispatch decisions through the strategy seam

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the reviewer

- After Task 4, `config.yaml`'s `strategy: hybrid` means production behavior is unchanged; switching to the new strategy is a one-line config edit (`strategy: indicator_rule`).
- The seam is intentionally minimal (a dict + a function). Backtesting (sub-project #2) will call `strategies.get(name)` and replay a strategy over historical candles — the deterministic `indicator_rule` is what makes that cheap.
