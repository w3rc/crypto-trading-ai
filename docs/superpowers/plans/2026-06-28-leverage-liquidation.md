# Leverage + Liquidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in leverage (>1×) and isolated-margin liquidation to the paper-trading engine, building on the live signed-position (shorting) core.

**Architecture:** Standard isolated-margin perp model. A position posts `margin = |qty|·avg/leverage`; opening locks margin, closing returns margin + realized P&L. Liquidation is a second force-close trigger price checked alongside the stop-loss, reusing the existing per-symbol stop-close path. `leverage = 1` is economically identical to today (longs byte-identical; the default spot config never shorts, so live behavior is unchanged).

**Tech Stack:** Python 3.14 engine (pytest, pydantic, pyyaml); Electron/TypeScript/React dashboard (vitest, node-env lib tests only).

## Global Constraints

- **TDD always:** red → green per step. Run the named command and confirm the stated result before moving on.
- **`leverage = 1.0` and the default spot/`allow_short`-off config must stay byte-identical** to current live behavior. Longs at `L=1` are identical; only opt-in shorts change cash bookkeeping (equity/P&L preserved).
- **Isolated margin only.** No cross margin, no per-symbol leverage, no insurance fund / partial-liquidation tiers, no funding (slice 3).
- **The risk gate stays the single authority.** No order bypasses `plan_order` → `apply_fill`; `|qty·price|` never exceeds `max_position_pct · equity · leverage`.
- **No new dependencies.** No `Date.now()`/network in engine logic.
- **Commit trailers** (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q`. Desktop: `cd desktop && npm test` and `npm run build`.
- The full design is `docs/superpowers/specs/2026-06-28-leverage-liquidation-design.md`.

---

### Task 1: Config + Position model (foundation)

**Files:**
- Modify: `engine/models.py` (Position gains `leverage`)
- Modify: `engine/config.py` (`RiskConfig` gains `leverage`, `maintenance_margin_pct`; `load_config` reads them)
- Modify: `engine/config.yaml` (document the two new risk knobs)
- Test: `tests/test_models.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `Position(symbol, qty=0.0, avg_price=0.0, stop_price=0.0, leverage=1.0)`; `RiskConfig(max_position_pct, stop_loss_pct, allow_short=None, leverage=1.0, maintenance_margin_pct=0.005)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
def test_position_default_leverage_is_one():
    p = Position(symbol="BTC/USDT")
    assert p.leverage == 1.0

def test_position_accepts_leverage():
    p = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert p.leverage == 5.0
```

Append to `tests/test_config.py`:

```python
def test_risk_leverage_and_mmr_default(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    cfg = load_config("engine/config.yaml")
    assert cfg.risk.leverage == 1.0                 # opt-in: off by default
    assert cfg.risk.maintenance_margin_pct == 0.005

def test_risk_leverage_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "  leverage: 5\n  maintenance_margin_pct: 0.004\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.risk.leverage == 5.0
    assert cfg.risk.maintenance_margin_pct == 0.004
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py::test_position_default_leverage_is_one tests/test_config.py::test_risk_leverage_and_mmr_default -q`
Expected: FAIL — `Position` has no `leverage` / `RiskConfig` has no `leverage`.

- [ ] **Step 3: Implement**

In `engine/models.py`, add the field to `Position`:

```python
@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    stop_price: float = 0.0
    leverage: float = 1.0
```

In `engine/config.py`, extend `RiskConfig`:

```python
@dataclass
class RiskConfig:
    max_position_pct: float
    stop_loss_pct: float
    allow_short: Optional[bool] = None
    leverage: float = 1.0
    maintenance_margin_pct: float = 0.005
```

In `engine/config.py` `load_config`, extend the `RiskConfig(...)` construction:

```python
        risk=RiskConfig(
            max_position_pct=float(raw["risk"]["max_position_pct"]),
            stop_loss_pct=float(raw["risk"]["stop_loss_pct"]),
            allow_short=raw["risk"].get("allow_short", None),
            leverage=float(raw["risk"].get("leverage", 1.0)),
            maintenance_margin_pct=float(raw["risk"].get("maintenance_margin_pct", 0.005)),
        ),
```

In `engine/config.yaml`, document the knobs under `risk:`:

```yaml
risk:
  max_position_pct: 0.25
  stop_loss_pct: 0.05
  # leverage: 1.0              # >1 enables isolated-margin leverage (opt-in)
  # maintenance_margin_pct: 0.005   # margin floor that triggers liquidation
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py tests/test_config.py -q`
Expected: PASS (all, including existing).

- [ ] **Step 5: Commit**

```bash
git add engine/models.py engine/config.py engine/config.yaml tests/test_models.py tests/test_config.py
git commit -m "feat: leverage + maintenance_margin_pct config and Position.leverage"
```

---

### Task 2: `liquidation_price` + `force_close` (pure, additive)

**Files:**
- Modify: `engine/broker.py` (add two functions; no change to existing behavior)
- Test: `tests/test_broker.py`

**Interfaces:**
- Consumes: `Position.leverage` (Task 1), `RiskConfig.maintenance_margin_pct` (Task 1), existing `stop_triggered`.
- Produces:
  - `liquidation_price(position, maintenance_margin_pct: float) -> float` — `0.0` when `leverage ≤ 1`, flat, or `avg ≤ 0`; long `avg·(1 − 1/L)/(1 − mmr)`; short `avg·(1 + 1/L)/(1 + mmr)`.
  - `force_close(position, price, risk) -> str | None` — `"liquidation"` (checked first), else `"stop-loss"`, else `None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_broker.py`:

```python
def test_liquidation_price_long():
    from engine.broker import liquidation_price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert liquidation_price(pos, 0.005) == pytest.approx(100 * (1 - 1/5) / (1 - 0.005))

def test_liquidation_price_short():
    from engine.broker import liquidation_price
    pos = Position("BTC/USDT", qty=-1.0, avg_price=100.0, stop_price=105.0, leverage=5.0)
    assert liquidation_price(pos, 0.005) == pytest.approx(100 * (1 + 1/5) / (1 + 0.005))

def test_liquidation_price_unleveraged_is_zero():
    from engine.broker import liquidation_price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=1.0)
    assert liquidation_price(pos, 0.005) == 0.0

def test_liquidation_price_flat_is_zero():
    from engine.broker import liquidation_price
    assert liquidation_price(Position("BTC/USDT", leverage=5.0), 0.005) == 0.0

def test_force_close_liquidation_outranks_stop():
    from engine.broker import force_close
    # 5x long, avg 100 -> liq ~80.4; price 80 is below BOTH the 95 stop and the liq price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert force_close(pos, 80.0, RISK_LEV) == "liquidation"

def test_force_close_stop_when_only_stop_hit():
    from engine.broker import force_close
    # price 90 is below the 95 stop but above the ~80.4 liq price
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert force_close(pos, 90.0, RISK_LEV) == "stop-loss"

def test_force_close_none_when_safe():
    from engine.broker import force_close
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0, leverage=5.0)
    assert force_close(pos, 120.0, RISK_LEV) is None
```

Add this fixture near the top of `tests/test_broker.py` (below the existing `RISK = ...` line):

```python
RISK_LEV = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05, leverage=5.0,
                      maintenance_margin_pct=0.005)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_broker.py -k "liquidation_price or force_close" -q`
Expected: FAIL — `liquidation_price` / `force_close` not defined.

- [ ] **Step 3: Implement**

In `engine/broker.py`, after `stop_triggered` (and before `_stop_price`), add:

```python
def liquidation_price(position: Position, maintenance_margin_pct: float) -> float:
    """Isolated-margin liquidation price; 0.0 means 'never' (unleveraged/flat)."""
    L = position.leverage
    avg = position.avg_price
    if L <= 1.0 or avg <= 0 or abs(position.qty) <= _EPS:
        return 0.0
    mmr = maintenance_margin_pct
    if position.qty > 0:
        return avg * (1 - 1.0 / L) / (1 - mmr)
    return avg * (1 + 1.0 / L) / (1 + mmr)


def force_close(position: Position, price: float, risk) -> str | None:
    """Why the position must be force-closed this cycle, if at all.

    Liquidation outranks the protective stop. Returns "liquidation",
    "stop-loss", or None.
    """
    liq = liquidation_price(position, getattr(risk, "maintenance_margin_pct", 0.005))
    if liq > 0:
        if position.qty > 0 and price <= liq:
            return "liquidation"
        if position.qty < 0 and price >= liq:
            return "liquidation"
    if stop_triggered(position, price):
        return "stop-loss"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broker.py -q`
Expected: PASS (new + all existing).

- [ ] **Step 5: Commit**

```bash
git add engine/broker.py tests/test_broker.py
git commit -m "feat: liquidation_price + force_close helper (isolated margin)"
```

---

### Task 3: `plan_order` — leverage-scaled cap + margin-bounded opens

**Files:**
- Modify: `engine/broker.py` (`plan_order`)
- Test: `tests/test_broker.py`

**Interfaces:**
- Consumes: `RiskConfig.leverage` (Task 1).
- Produces: `plan_order` unchanged signature; cap is now `max_position_pct · equity · leverage`; opens (long and short) are bounded by `cash · leverage`.

**Note — intended slice-2 tightening:** an isolated short now requires collateral, so two slice-1 short-gate tests that opened a short from a **zero-cash** account are updated to fund the margin. Economics (equity/P&L) are unchanged; only the precondition tightens.

- [ ] **Step 1: Write the failing tests + update the two slice-1 short-gate tests**

Append new tests to `tests/test_broker.py`:

```python
def test_buy_cap_scales_with_leverage():
    # equity 1000, cap 0.25 -> 250 at 1x; 5x lifts the cap to 1250 notional / 10 = 125
    risk = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05, leverage=5.0)
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=10000, price=10, equity=1000, risk=risk)
    assert o.qty == pytest.approx(125.0)

def test_buy_open_bounded_by_cash_times_leverage():
    # only 100 cash, 5x -> can open up to 100*5=500 notional / 10 = 50 (margin-bounded)
    risk = RiskConfig(max_position_pct=1.0, stop_loss_pct=0.05, leverage=5.0)
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=100, price=10, equity=1_000_000, risk=risk)
    assert o.qty == pytest.approx(50.0)

def test_short_open_bounded_by_cash_times_leverage():
    # short open now needs margin: 100 cash, 5x -> 500 notional / 10 = 50
    risk = RiskConfig(max_position_pct=1.0, stop_loss_pct=0.05, leverage=5.0, allow_short=True)
    o = plan_order(Decision(action="sell", size=1.0),
                   Position("BTC/USDT"), cash=100, price=10, equity=1_000_000, risk=risk)
    assert o.side == "sell" and o.qty == pytest.approx(50.0)
```

Update the two existing slice-1 short-gate tests in `tests/test_broker.py` to fund the margin (change `cash=0` → `cash=10000`):

```python
def test_sell_when_flat_opens_short_capped():
    # equity 1000 -> cap 250; sell from flat opens a short up to the cap (needs margin now)
    o = plan_order(Decision(action="sell", size=1.0),
                   Position("BTC/USDT"), cash=10000, price=10, equity=1000, risk=RISK_S)
    assert o.side == "sell" and o.qty == pytest.approx(25.0)   # 250 notional / 10

def test_sell_extends_short_up_to_cap():
    pos = Position("BTC/USDT", qty=-10, avg_price=10, stop_price=10.5)  # short notional 100
    o = plan_order(Decision(action="sell", size=1.0), pos, cash=10000, price=10, equity=1000, risk=RISK_S)
    assert o.qty == pytest.approx(15.0)    # remaining short headroom 250-100=150 / 10
```

- [ ] **Step 2: Run to verify the new ones fail**

Run: `python -m pytest tests/test_broker.py -k "leverage or cash_times_leverage" -q`
Expected: FAIL — cap not yet scaled by leverage.

- [ ] **Step 3: Implement**

Replace the body of `plan_order` in `engine/broker.py` (keep the docstring) from the `allow_short = ...` line through the final `return None`:

```python
    allow_short = bool(getattr(risk, "allow_short", False))   # None/False -> long-only
    lev = max(1.0, getattr(risk, "leverage", 1.0))
    qty = position.qty
    max_value = risk.max_position_pct * equity * lev          # leverage scales the cap

    if decision.action == "buy":
        if qty < 0:                                   # cover a short -> clamp at flat
            q = min(decision.size * equity * lev / price, -qty)
        else:                                         # open/extend long
            headroom = max(0.0, max_value - qty * price)
            q = min(decision.size * equity * lev, headroom, cash * lev) / price
        if q * price < _EPS:
            return None
        return Order(side="buy", qty=q, price=price)

    if decision.action == "sell":
        if qty > 0:                                   # reduce long -> clamp at flat
            q = min(decision.size * qty, qty)
        elif allow_short:                             # open/extend short (needs margin)
            short_headroom = max(0.0, max_value - (-qty) * price)
            q = min(decision.size * equity * lev, short_headroom, cash * lev) / price
        else:
            return None                               # spot long-only
        if q * price < _EPS:
            return None
        return Order(side="sell", qty=q, price=price)

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_broker.py -q`
Expected: PASS (new + updated + all existing — at `leverage=1` every branch reduces to slice 1 except the short-open cash bound, covered by the two updated tests).

- [ ] **Step 5: Commit**

```bash
git add engine/broker.py tests/test_broker.py
git commit -m "feat: plan_order leverage-scaled cap + margin-bounded opens"
```

---

### Task 4: `apply_fill` — isolated-margin accounting + `leverage`

**Files:**
- Modify: `engine/broker.py` (`apply_fill`)
- Test: `tests/test_broker.py`

**Interfaces:**
- Consumes: `Position.leverage` (Task 1).
- Produces: `apply_fill(order, position, cash, fee_pct, slippage_pct, stop_loss_pct, ts, leverage=1.0) -> (Position, float, Fill)`. Opening/extending locks `margin = added_notional/leverage`; reducing/closing returns `released_margin + realized_pnl`; reduces clamp at flat (no single-order flip); cash is clamped `≥ 0` (bad debt).

**Note — slice-1 assertion updates (all economics preserved):**
- `test_open_short_sets_negative_qty_and_stop_above`: `cash2 == 1200.0` → `cash2 == 800.0` (margin locked, not proceeds received).
- `test_sell_beyond_long_flips_to_short` → rewritten to `test_sell_beyond_long_clamps_at_flat` (reduces clamp at flat; no flip).
- `test_cover_clamped_when_cash_short_no_crash` → rewritten as a bad-debt-clamp test (cover releases margin; a gap past liquidation clamps cash to 0, no crash).

- [ ] **Step 1: Write/Update the tests**

Append new margin-accounting tests to `tests/test_broker.py`:

```python
def test_open_long_locks_margin_not_full_notional():
    from engine.broker import apply_fill
    from engine.models import Order
    # 5x: opening 5 @ 100 (notional 500) locks only 500/5 = 100 of cash
    pos2, cash2, _ = apply_fill(Order("buy", 5.0, 100.0), Position("BTC/USDT"), 1000.0,
                                0.0, 0.0, 0.05, "t", leverage=5.0)
    assert pos2.qty == pytest.approx(5.0)
    assert pos2.avg_price == pytest.approx(100.0)
    assert pos2.leverage == 5.0
    assert cash2 == pytest.approx(900.0)          # 1000 - 100 margin (not 500)

def test_leveraged_long_roundtrip_pnl_matches_unleveraged():
    from engine.broker import apply_fill
    from engine.models import Order
    # leverage changes margin, not absolute P&L: +10 move on 1 unit = +10 either way
    pos2, cash2, _ = apply_fill(Order("buy", 1.0, 100.0), Position("BTC/USDT"), 1000.0,
                                0.0, 0.0, 0.05, "t", leverage=5.0)
    pos3, cash3, _ = apply_fill(Order("sell", 1.0, 110.0), pos2, cash2,
                                0.0, 0.0, 0.05, "t2", leverage=5.0)
    assert pos3.qty == 0.0
    assert cash3 == pytest.approx(1010.0)         # +10 profit, same as 1x

def test_bad_debt_cover_clamps_cash_to_zero_no_crash():
    from engine.broker import apply_fill
    from engine.models import Order
    # underwater short, price gapped far past liquidation: cover realizes a loss
    # bigger than released margin -> cash clamps to 0 (bad debt), never negative/crash
    pos = Position("BTC/USDT", qty=-1.0, avg_price=100.0, stop_price=105.0)
    pos2, cash2, fill = apply_fill(Order("buy", 1.0, 250.0), pos, 10.0, 0.0, 0.0, 0.05, "t")
    assert fill.qty == pytest.approx(1.0)         # fully covers (margin released)
    assert pos2.qty == 0.0
    assert cash2 == 0.0                            # bad-debt clamp, no crash
```

Update `test_open_short_sets_negative_qty_and_stop_above` (change the cash assertion):

```python
def test_open_short_sets_negative_qty_and_stop_above():
    from engine.broker import apply_fill
    from engine.models import Order
    pos2, cash2, _ = apply_fill(Order("sell", 2.0, 100.0), Position("BTC/USDT"), 1000.0,
                                0.0, 0.0, 0.05, "t")
    assert pos2.qty == pytest.approx(-2.0)
    assert pos2.avg_price == pytest.approx(100.0)
    assert pos2.stop_price == pytest.approx(105.0)     # 100*(1+0.05)
    assert cash2 == pytest.approx(800.0)               # isolated margin: 1000 - 200 locked
```

Replace `test_sell_beyond_long_flips_to_short` with:

```python
def test_sell_beyond_long_clamps_at_flat():
    from engine.broker import apply_fill
    from engine.models import Order
    # a sell larger than the long reduces to flat (no single-order flip; gate forbids it)
    pos = Position("BTC/USDT", qty=1.0, avg_price=100.0, stop_price=95.0)
    pos2, _, fill = apply_fill(Order("sell", 5.0, 100.0), pos, 0.0, 0.0, 0.0, 0.05, "t")
    assert pos2.qty == 0.0                             # closed to flat, not flipped
    assert fill.qty == pytest.approx(1.0)              # only the 1 unit to flat filled
```

Delete the old `test_cover_clamped_when_cash_short_no_crash` (replaced by `test_bad_debt_cover_clamps_cash_to_zero_no_crash` above).

- [ ] **Step 2: Run to verify the new ones fail (or assert wrong values)**

Run: `python -m pytest tests/test_broker.py -k "locks_margin or roundtrip_pnl_matches or bad_debt" -q`
Expected: FAIL — `apply_fill` doesn't take `leverage` / still uses full-notional accounting.

- [ ] **Step 3: Implement**

Replace the entire `apply_fill` function in `engine/broker.py` with:

```python
def apply_fill(order: Order, position: Position, cash: float, fee_pct: float,
               slippage_pct: float, stop_loss_pct: float, ts: str,
               leverage: float = 1.0):
    """Simulate a fill on a signed, isolated-margin position.

    Opening/extending locks margin = added_notional/leverage; reducing/closing
    returns released_margin + realized P&L. Reduces clamp at flat (the gate
    forbids single-order flips). leverage=1 is the spot model for longs and an
    isolated short for shorts. Returns (new_position, new_cash, fill).
    """
    old_qty = position.qty
    avg = position.avg_price
    L = position.leverage if abs(old_qty) > _EPS else max(1.0, leverage)

    if order.side == "buy":
        eff = order.price * (1 + slippage_pct)
        if old_qty < 0:                               # cover (reduce/close short)
            filled = min(order.qty, -old_qty)         # clamp at flat (no flip)
            realized = filled * (avg - eff)
            new_cash = cash + filled * avg / L + realized - filled * eff * fee_pct
        else:                                         # open/extend long
            # ponytail: margin-clamp defensively so an over-ask can't overspend or
            # crash; the gate already bounds opens to cash*L in production.
            afford = cash / (eff * (1.0 / L + fee_pct)) if eff > 0 else 0.0
            filled = min(order.qty, max(0.0, afford))
            new_cash = cash - filled * eff * (1.0 / L + fee_pct)
    else:                                             # sell
        eff = order.price * (1 - slippage_pct)
        if old_qty > 0:                               # reduce/close long
            filled = min(order.qty, old_qty)          # clamp at flat (no flip)
            realized = filled * (eff - avg)
            new_cash = cash + filled * avg / L + realized - filled * eff * fee_pct
        else:                                         # open/extend short (needs margin)
            afford = cash / (eff * (1.0 / L + fee_pct)) if eff > 0 else 0.0
            filled = min(order.qty, max(0.0, afford))
            new_cash = cash - filled * eff * (1.0 / L + fee_pct)

    fee = filled * eff * fee_pct
    new_qty = old_qty + filled if order.side == "buy" else old_qty - filled

    if abs(new_qty) <= _EPS:                          # closed to flat
        new_pos = Position(position.symbol, 0.0, 0.0, 0.0, 1.0)
    elif old_qty == 0 or ((old_qty > 0) == (new_qty > 0) and abs(new_qty) > abs(old_qty)):
        new_avg = (abs(old_qty) * avg + filled * eff) / abs(new_qty)   # open/extend
        new_pos = Position(position.symbol, new_qty, new_avg,
                           _stop_price(new_avg, new_qty, stop_loss_pct), L)
    else:                                             # reduced toward flat
        new_pos = Position(position.symbol, new_qty, avg, position.stop_price, L)

    # ponytail: a gap past the liquidation price is bad debt; clamp cash >= 0
    # (socialized). Insurance fund is the upgrade path.
    return new_pos, max(0.0, new_cash), Fill(position.symbol, order.side, filled, eff, fee, ts)
```

- [ ] **Step 4: Run the full broker suite**

Run: `python -m pytest tests/test_broker.py -q`
Expected: PASS — new margin tests, the three updated/rewritten tests, and every unchanged slice-1 test (longs identical; `test_short_profit_when_price_falls` still ends at `cash == 1010`; `test_partial_sell_preserves_avg_and_stop` still `cash == 440`; `test_buy_clamped_to_cash_no_crash` still partial).

- [ ] **Step 5: Commit**

```bash
git add engine/broker.py tests/test_broker.py
git commit -m "feat: apply_fill isolated-margin accounting (leverage, no flip, bad-debt clamp)"
```

---

### Task 5: State — margin-aware equity, persist leverage, write `liq_price`

**Files:**
- Modify: `engine/state.py` (`position_value` helper, `equity`, `save_state_atomic`, `load_state`)
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `broker.liquidation_price` (Task 2), `Position.leverage` (Task 1).
- Produces:
  - `position_value(p, price) -> float` = `|qty|·avg/leverage + qty·(price − avg)` (margin + unrealized).
  - `equity(state, price_map)` uses `position_value`.
  - `save_state_atomic(state, data_dir, maintenance_margin_pct=0.005)` — each saved position dict gains a computed `liq_price`.
  - `load_state` strips `liq_price` (and any non-`Position` keys) before reconstructing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
def test_equity_unchanged_for_long_book(tmp_path):
    st = load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=500.0)  # 1x long
    assert equity(st, {"BTC/USDT": 600.0}) == 1000.0 + 2.0 * 600.0   # == old cash+qty*price

def test_equity_leveraged_long_is_margin_plus_unrealized(tmp_path):
    st = load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=500.0, leverage=5.0)
    # margin 2*500/5 = 200; unrealized 2*(600-500) = 200
    assert equity(st, {"BTC/USDT": 600.0}) == 1000.0 + 200.0 + 200.0

def test_save_load_preserves_leverage(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=100.0,
                                         stop_price=95.0, leverage=5.0)
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].leverage == 5.0

def test_snapshot_includes_liq_price_for_leveraged(tmp_path):
    import json
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=100.0,
                                         stop_price=95.0, leverage=5.0)
    save_state_atomic(st, str(tmp_path), maintenance_margin_pct=0.005)
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["positions"]["BTC/USDT"]["liq_price"] > 0    # written for the dashboard
    # and a snapshot carrying liq_price reloads cleanly (key stripped)
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 1.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_state.py -k "leveraged or preserves_leverage or liq_price" -q`
Expected: FAIL — `equity` uses the old formula / no `liq_price` written / `Position(**p)` chokes on `liq_price`.

- [ ] **Step 3: Implement**

In `engine/state.py`, add the `broker` import at the top (next to the models import):

```python
from engine import broker
from engine.models import Position, Fill
```

Add a module-level constant and the helper, and rewrite `equity`:

```python
_POS_FIELDS = {"symbol", "qty", "avg_price", "stop_price", "leverage"}


def position_value(p, price: float) -> float:
    """Account value of a position: margin + unrealized P&L (isolated margin)."""
    lev = getattr(p, "leverage", 1.0) or 1.0
    return abs(p.qty) * p.avg_price / lev + p.qty * (price - p.avg_price)


def equity(state: State, price_map: dict) -> float:
    return state.cash + sum(position_value(p, price_map.get(s, p.avg_price))
                            for s, p in state.positions.items())
```

(Delete the old `equity` body that summed `p.qty * price_map.get(...)`.)

Rewrite `load_state`'s positions reconstruction to strip non-`Position` keys:

```python
    positions = {s: Position(**{k: v for k, v in p.items() if k in _POS_FIELDS})
                 for s, p in raw["positions"].items()}
```

Rewrite `save_state_atomic` to accept `maintenance_margin_pct` and add `liq_price`:

```python
def save_state_atomic(state: State, data_dir: str,
                      maintenance_margin_pct: float = 0.005) -> None:
    os.makedirs(data_dir, exist_ok=True)
    payload = {
        "cash": state.cash,
        "positions": {s: {**vars(p),
                          "liq_price": broker.liquidation_price(p, maintenance_margin_pct)}
                      for s, p in state.positions.items()},
        "equity_history": state.equity_history,
    }
    path = _state_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)                   # atomic on POSIX
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_state.py -q`
Expected: PASS (new + existing; `test_equity_uses_avg_price_when_missing` and `test_save_then_load_roundtrip` still pass — long/1× equity and roundtrip unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/state.py tests/test_state.py
git commit -m "feat: margin-aware equity, persist leverage, write liq_price into snapshot"
```

---

### Task 6: Loop wiring — `force_close` + leverage in bot & backtest

**Files:**
- Modify: `engine/bot.py` (force-close block; pass `leverage` to `apply_fill`; pass `mmr` to `save_state_atomic`)
- Modify: `engine/backtest.py` (force-close block; pass `leverage` to `apply_fill`; margin-aware equity)
- Test: `tests/test_bot.py`, `tests/test_backtest.py`

**Interfaces:**
- Consumes: `broker.force_close` (Task 2), `apply_fill(..., leverage=)` (Task 4), `state.position_value` (Task 5).
- Produces: liquidation is checked before the strategy each cycle; the decision log records `reason="liquidation"` distinctly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
def test_leveraged_position_liquidated_on_adverse_move(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.risk.leverage = 5.0
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 0.0
    # 5x long, avg 210 -> liq ~168.8; stop sits low (1.0) so only liquidation can fire.
    # current price 159 is below the liq price -> must force-close as a liquidation.
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=210.0,
                                         stop_price=1.0, leverage=5.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path), cfg.risk.maintenance_margin_pct)
    bot.run_once(cfg, market=FakeMarket(price=159.0), strategy=_strat(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0          # force-closed
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["reason"] == "liquidation"
```

Append to `tests/test_backtest.py` (reuses the file's existing `_cfg` / `_candles` / `_feed_for` / `_always` helpers):

```python
def test_backtest_runs_with_leverage(tmp_path):
    # leverage must not crash the replay and must still produce aligned curves
    cfg = _cfg(tmp_path, ["BTC/USDT"])
    cfg.risk.leverage = 3.0
    feed = _feed_for({"BTC/USDT": _candles(60)})
    r = backtest.run_backtest(["BTC/USDT"], "1h", 0, 60 * TF_MS, "indicator_rule", cfg,
                              feed=feed, strategy=_always(Decision(action="buy", size=0.5)))
    assert len(r["equity_curve"]) == len(r["buy_hold_curve"])
    assert isinstance(r["metrics"]["final_equity"], float)
    assert len(r["trades"]) > 0                  # leverage lets the buy fill
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bot.py::test_leveraged_position_liquidated_on_adverse_move -q`
Expected: FAIL — decision reason is `"stop-loss"`/absent (no `force_close` wiring) or position not closed.

- [ ] **Step 3: Implement**

In `engine/bot.py`, replace the force-close block (currently `if broker.stop_triggered(pos, price): ... else: ...`) with:

```python
            reason = broker.force_close(pos, price, cfg.risk)
            if reason:                                # "liquidation" | "stop-loss"
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strategy(feats, pos, st.cash, cfg)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason
```

In `engine/bot.py`, pass leverage to `apply_fill`:

```python
            new_pos, new_cash, fill = broker.apply_fill(
                order, pos, st.cash, cfg.fee_pct, cfg.slippage_pct,
                cfg.risk.stop_loss_pct, ts, cfg.risk.leverage)
```

In `engine/bot.py`, pass `mmr` to the persistence call:

```python
            state_mod.save_state_atomic(st, cfg.data_dir, cfg.risk.maintenance_margin_pct)
```

In `engine/backtest.py`, add the state import:

```python
from engine import broker, datafeed, indicators, market, metrics, sentiment, state, strategies
```

Replace the two inline equity computations (lines computing `cash + sum(positions[s].qty * prices[s] ...)`) with the margin-aware helper:

```python
        equity = cash + sum(state.position_value(positions[s], prices[s]) for s in symbols)
```

and

```python
        equity_curve.append(cash + sum(state.position_value(positions[s], prices[s]) for s in symbols))
```

Replace the backtest force-close block:

```python
            reason = broker.force_close(pos, price, cfg.risk)
            if reason:
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strat(feats[sym], pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
```

And pass leverage to the backtest `apply_fill`:

```python
                positions[sym], cash, fill = broker.apply_fill(
                    order, pos, cash, cfg.fee_pct, cfg.slippage_pct,
                    cfg.risk.stop_loss_pct, _iso(ts), cfg.risk.leverage)
```

- [ ] **Step 4: Run the engine suite**

Run: `python -m pytest -q`
Expected: PASS — full suite green (existing stop/short tests still pass: `force_close` returns `"stop-loss"` at `leverage=1` exactly where `stop_triggered` did).

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py engine/backtest.py tests/test_bot.py tests/test_backtest.py
git commit -m "feat: wire force_close + leverage through bot and backtest loops"
```

---

### Task 7: Dashboard — Leverage + Liq. price columns

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`Position` type gains `leverage?`, `liq_price?`)
- Modify: `desktop/src/lib/position.ts` (`leverageLabel`, `liqLabel` helpers)
- Modify: `desktop/src/renderer/src/components/PositionsTable.tsx` (two columns)
- Test: `desktop/src/lib/position.test.ts`

**Interfaces:**
- Consumes: the engine snapshot's per-position `leverage` and `liq_price` (Task 5).
- Produces: `leverageLabel(lev?: number) -> string` (e.g. `"5×"`, `"1×"`); `liqLabel(liq?: number) -> string` (`"$123.45"` or `"—"`).

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/lib/position.test.ts`:

```typescript
import { leverageLabel, liqLabel } from "./position";

test("leverageLabel formats with x suffix", () => {
  expect(leverageLabel(5)).toBe("5×");
  expect(leverageLabel(1)).toBe("1×");
  expect(leverageLabel(undefined)).toBe("1×");
});

test("liqLabel shows price or dash", () => {
  expect(liqLabel(123.456)).toBe("$123.46");
  expect(liqLabel(0)).toBe("—");
  expect(liqLabel(undefined)).toBe("—");
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/lib/position.test.ts`
Expected: FAIL — `leverageLabel` / `liqLabel` not exported.

- [ ] **Step 3: Implement**

Append to `desktop/src/lib/position.ts`:

```typescript
export function leverageLabel(lev?: number): string {
  return `${lev ?? 1}×`;
}

export function liqLabel(liq?: number): string {
  return liq && liq > 0 ? `$${liq.toFixed(2)}` : "—";
}
```

In `desktop/src/lib/parse.ts`, extend the `Position` type:

```typescript
export type Position = { symbol?: string; qty: number; avg_price: number; stop_price: number;
                         leverage?: number; liq_price?: number };
```

In `desktop/src/renderer/src/components/PositionsTable.tsx`, import the helpers and add the columns:

```tsx
import type { State } from "../../../lib/parse";
import { positionSide, leverageLabel, liqLabel } from "../../../lib/position";

export default function PositionsTable({ state }: { state: State | null }) {
  const positions = state ? Object.entries(state.positions).filter(([, p]) => p.qty !== 0) : [];
  if (positions.length === 0) return <div className="empty">Flat — no open positions.</div>;
  return (
    <table>
      <thead>
        <tr><th>Symbol</th><th>Side</th><th className="right">Qty</th><th className="right">Avg price</th><th className="right">Lev</th><th className="right">Liq. price</th><th className="right">Stop</th></tr>
      </thead>
      <tbody>
        {positions.map(([sym, p]) => (
          <tr key={sym}>
            <td>{sym}</td>
            <td>{positionSide(p.qty)}</td>
            <td className="right">{p.qty.toFixed(6)}</td>
            <td className="right">${p.avg_price.toFixed(2)}</td>
            <td className="right">{leverageLabel(p.leverage)}</td>
            <td className="right muted">{liqLabel(p.liq_price)}</td>
            <td className="right muted">${p.stop_price.toFixed(2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Run lib tests + build**

Run: `cd desktop && npm test && npm run build`
Expected: vitest PASS (incl. new helpers); build exits 0.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/lib/position.ts desktop/src/lib/position.test.ts desktop/src/renderer/src/components/PositionsTable.tsx
git commit -m "feat: dashboard PositionsTable shows leverage + liquidation price"
```

---

### Task 8: README + final verification

**Files:**
- Modify: `README.md` (document leverage + maintenance margin + liquidation)
- Test: full suites + Playwright visual check

- [ ] **Step 1: Update README**

Add to the risk/derivatives section of `README.md` a short note (match the existing prose/code-fence style):

> **Leverage + liquidation (opt-in, isolated margin).** Set `risk.leverage` > 1 to trade with leverage; each position posts `margin = |qty|·avg / leverage` and is **liquidated** at its isolated liquidation price when an adverse move erodes that margin to `risk.maintenance_margin_pct` (default 0.5%). The protective stop-loss still fires first on low leverage; liquidation is the high-leverage / gap backstop. `leverage = 1` (the default) is unleveraged and never liquidates. Like shorting, this only activates on a derivatives venue or explicit config — the default spot setup is unchanged.

- [ ] **Step 2: Full engine + desktop suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest green; build exit 0.

- [ ] **Step 3: Playwright visual verification**

Build the renderer, serve a snapshot containing a leveraged position (`leverage: 5`, a positive `liq_price`), and screenshot `PositionsTable` at 1280 / 768 / 375 px. Confirm the Lev (`5×`) and Liq. price columns render and the layout holds. Clean up any harness artifacts after.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document leverage + liquidation (isolated margin, opt-in)"
```

---

## Self-Review

**Spec coverage:**
- Config (`leverage`, `maintenance_margin_pct`) + `Position.leverage` → Task 1 ✓
- `liquidation_price` + `force_close` → Task 2 ✓
- `plan_order` leverage-scaled cap + margin-bounded opens → Task 3 ✓
- `apply_fill` isolated-margin accounting, no-flip, bad-debt clamp, `leverage` arg → Task 4 ✓
- Margin-aware `equity`, persist `leverage`, write `liq_price` → Task 5 ✓
- bot + backtest force-close + leverage wiring → Task 6 ✓
- Dashboard Leverage + Liq. price columns → Task 7 ✓
- README + Playwright → Task 8 ✓
- Slice-1 compatibility (longs identical; short tightening documented; the 4 changed assertions enumerated) → Tasks 3 & 4 ✓

**Type/signature consistency:** `apply_fill(..., ts, leverage=1.0)` — Task 4 defines, Task 6 calls with `cfg.risk.leverage` positionally as the 8th arg ✓. `force_close(position, price, risk)` — Task 2 defines, Task 6 calls ✓. `liquidation_price(position, mmr)` — Task 2 defines, Tasks 5 (`save_state_atomic`) and 2 (`force_close`) call ✓. `position_value(p, price)` — Task 5 defines, Task 6 (backtest) calls ✓. `leverageLabel`/`liqLabel` — Task 7 defines + consumes ✓.

**Placeholder scan:** no TBD/TODO; every code step shows full code. The Task 6 backtest test uses the file's real `_cfg`/`_candles`/`_feed_for`/`_always` fixtures (verified against `tests/test_backtest.py`).
