# Crypto Paper-Trading Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python engine of an AI-driven crypto **paper-trading** bot: one cron-triggered decision cycle that fetches market data, computes indicators, asks an LLM for a buy/sell/hold call, clamps it through a deterministic risk gate, simulates the fill, and persists state + a trade log.

**Architecture:** Stateless-per-run. `bot.run_once()` loads state from `data/`, processes each symbol (ccxt data → indicators → LLM decision → risk gate → paper fill), writes state atomically, and exits. The LLM proposes; deterministic code disposes. Any error → HOLD. Side-effectful concerns (network, disk, LLM) live in isolated modules so the logic is unit-testable with fakes.

**Tech Stack:** Python 3.12 · `ccxt` (market data) · `pandas` (indicators, hand-rolled — no `pandas-ta`) · `openai` (OpenAI-compatible LLM client, any `base_url`) · `pydantic` (validate LLM output) · `pyyaml` · `pytest` · stdlib `json`/`csv`/`logging`/`fcntl`.

## Global Constraints

- **Python 3.12.** Paper trading only — NO real exchange orders anywhere in this plan.
- **Spot long-only.** Positions never go negative. No shorting, margin, or derivatives.
- **Fail-safe = HOLD.** Any error (network, malformed LLM output, bad data) results in doing nothing that cycle. Never trade on uncertainty.
- **The risk gate is authoritative.** The LLM's raw `size` never reaches the broker unclamped. Code caps every order to: ≤ `max_position_pct` of equity, ≤ available cash (buys), ≤ held quantity (sells).
- **LLM default:** OpenAI-compatible, `base_url=https://ai.myhermes.cloud/v1`, `model=z-ai/glm-5.2`, key from env var `MYHERMES_API_KEY`. Swappable via `config.yaml` (OpenRouter / custom endpoint).
- **State writes are atomic** (temp file + `os.replace`). A crash mid-write must not corrupt `data/state.json`.
- **One cycle at a time** — `data/bot.lock` (`fcntl.flock`, non-blocking); a second concurrent run exits immediately.
- Indicator defaults: RSI 14, MACD 12/26/9, SMA fast 20 / slow 50, ATR 14. Risk defaults: `max_position_pct=0.25`, `stop_loss_pct=0.05`. Broker defaults: `fee_pct=0.001`, `slippage_pct=0.0005`. Paper capital: `10000.0`.

---

## File Structure

```
engine/
  models.py        # Decision (pydantic) + Position/Order/Fill dataclasses — shared types, no logic
  config.py        # Config dataclasses + load_config() (yaml + env)
  indicators.py    # compute_indicators(df) -> dict  (pure, pandas only)
  broker.py        # plan_order() + stop_triggered() + apply_fill()  (pure money/risk logic)
  state.py         # load/save state atomically, append trades.csv, equity(), file lock
  market.py        # ccxt wrapper: make_exchange / fetch_ohlcv_df / fetch_price
  llm.py           # decide(): build prompt, call OpenAI-compatible endpoint, validate -> Decision, HOLD on failure
  bot.py           # run_once(): one decision cycle + __main__ entrypoint
  config.yaml      # symbols, capital, risk, llm provider/model, data_dir
  __init__.py
data/              # runtime, gitignored: state.json, trades.csv, bot.lock
tests/
  test_config.py  test_indicators.py  test_broker.py  test_state.py  test_llm.py  test_market.py  test_bot.py
requirements.txt
.env.example
.gitignore
```

Each module has one responsibility. `models.py` is shared types only (breaks import cycles). `broker.py` / `indicators.py` are pure (no I/O) and get the heaviest tests. `market.py` / `llm.py` / `state.py` wrap the side effects so `bot.py` can be tested with fakes.

---

### Task 1: Project scaffold + config loading

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.env.example`, `engine/__init__.py`, `engine/config.yaml`, `engine/config.py`, `data/.gitkeep`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Config`, `RiskConfig`, `LLMConfig` dataclasses and `load_config(path="engine/config.yaml") -> Config`. `Config` fields: `exchange:str`, `symbols:list[str]`, `timeframe:str`, `paper_capital:float`, `fee_pct:float`, `slippage_pct:float`, `data_dir:str`, `risk:RiskConfig`, `llm:LLMConfig`. `RiskConfig`: `max_position_pct:float`, `stop_loss_pct:float`. `LLMConfig`: `base_url:str`, `api_key:str`, `model:str`, `json_mode:bool`.

- [ ] **Step 1: Create dependency + ignore files**

`requirements.txt`:
```
ccxt
pandas
openai
pydantic
pyyaml
pytest
```

`.gitignore`:
```
__pycache__/
*.pyc
.env
.venv/
data/state.json
data/trades.csv
data/bot.lock
.pytest_cache/
.superpowers/
```

`.env.example`:
```
MYHERMES_API_KEY=sk-replace-me
```

`engine/__init__.py`: empty file. `data/.gitkeep`: empty file.

- [ ] **Step 2: Create `engine/config.yaml`**

```yaml
exchange: binance
symbols: [BTC/USDT, ETH/USDT]
timeframe: 15m
paper_capital: 10000.0
fee_pct: 0.001
slippage_pct: 0.0005
data_dir: data
risk:
  max_position_pct: 0.25
  stop_loss_pct: 0.05
llm:
  base_url: https://ai.myhermes.cloud/v1
  api_key_env: MYHERMES_API_KEY
  model: z-ai/glm-5.2
  json_mode: true
```

- [ ] **Step 3: Write the failing test** — `tests/test_config.py`

```python
import os
from engine.config import load_config

def test_load_config_defaults(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "test-key-123")
    cfg = load_config("engine/config.yaml")
    assert cfg.exchange == "binance"
    assert cfg.symbols == ["BTC/USDT", "ETH/USDT"]
    assert cfg.paper_capital == 10000.0
    assert cfg.risk.max_position_pct == 0.25
    assert cfg.llm.model == "z-ai/glm-5.2"
    assert cfg.llm.base_url == "https://ai.myhermes.cloud/v1"
    assert cfg.llm.api_key == "test-key-123"   # resolved from api_key_env
    assert cfg.llm.json_mode is True

def test_load_config_missing_key_is_empty_not_error(monkeypatch):
    monkeypatch.delenv("MYHERMES_API_KEY", raising=False)
    cfg = load_config("engine/config.yaml")
    assert cfg.llm.api_key == ""   # absent key -> "" (tests/mocks don't need it)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.config'`

- [ ] **Step 5: Write `engine/config.py`**

```python
import os
from dataclasses import dataclass

import yaml


@dataclass
class RiskConfig:
    max_position_pct: float
    stop_loss_pct: float


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    json_mode: bool


@dataclass
class Config:
    exchange: str
    symbols: list[str]
    timeframe: str
    paper_capital: float
    fee_pct: float
    slippage_pct: float
    data_dir: str
    risk: RiskConfig
    llm: LLMConfig


def load_config(path: str = "engine/config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f)
    llm = raw["llm"]
    return Config(
        exchange=raw["exchange"],
        symbols=list(raw["symbols"]),
        timeframe=raw["timeframe"],
        paper_capital=float(raw["paper_capital"]),
        fee_pct=float(raw["fee_pct"]),
        slippage_pct=float(raw["slippage_pct"]),
        data_dir=raw["data_dir"],
        risk=RiskConfig(
            max_position_pct=float(raw["risk"]["max_position_pct"]),
            stop_loss_pct=float(raw["risk"]["stop_loss_pct"]),
        ),
        llm=LLMConfig(
            base_url=llm["base_url"],
            api_key=os.environ.get(llm["api_key_env"], ""),
            model=llm["model"],
            json_mode=bool(llm.get("json_mode", True)),
        ),
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore .env.example engine/ data/.gitkeep tests/test_config.py
git commit -m "feat: project scaffold + config loading"
```

---

### Task 2: Shared types (`models.py`)

**Files:**
- Create: `engine/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Decision(BaseModel)` with `action:Literal["buy","sell","hold"]`, `size:float=0.0` (clamped 0–1), `reason:str=""`, `stop:float|None=None`; dataclasses `Position(symbol:str, qty:float=0.0, avg_price:float=0.0, stop_price:float=0.0)`, `Order(side:str, qty:float, price:float)`, `Fill(symbol:str, side:str, qty:float, price:float, fee:float, ts:str)`.

- [ ] **Step 1: Write the failing test** — `tests/test_models.py`

```python
import pytest
from pydantic import ValidationError
from engine.models import Decision, Position, Order, Fill

def test_decision_clamps_size():
    assert Decision(action="buy", size=5.0).size == 1.0
    assert Decision(action="buy", size=-2.0).size == 0.0

def test_decision_rejects_bad_action():
    with pytest.raises(ValidationError):
        Decision(action="moon")

def test_decision_ignores_extra_fields():
    d = Decision(action="hold", confidence=0.9)  # extra key ignored
    assert d.action == "hold"

def test_position_defaults_flat():
    p = Position(symbol="BTC/USDT")
    assert p.qty == 0.0 and p.avg_price == 0.0 and p.stop_price == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.models'`

- [ ] **Step 3: Write `engine/models.py`**

```python
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class Decision(BaseModel):
    action: Literal["buy", "sell", "hold"]
    size: float = 0.0
    reason: str = ""
    stop: Optional[float] = None

    @field_validator("size")
    @classmethod
    def _clamp_size(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    stop_price: float = 0.0


@dataclass
class Order:
    side: str  # "buy" | "sell"
    qty: float
    price: float


@dataclass
class Fill:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    ts: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/models.py tests/test_models.py
git commit -m "feat: shared types (Decision, Position, Order, Fill)"
```

---

### Task 3: Indicators (`indicators.py`)

**Files:**
- Create: `engine/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Consumes: a `pandas.DataFrame` with columns `open,high,low,close,volume`.
- Produces: `compute_indicators(df) -> dict` with float keys `price,rsi,macd,macd_signal,ma_fast,ma_slow,atr`. Raises `ValueError` if `len(df) < 50`. `MIN_ROWS = 50`.

- [ ] **Step 1: Write the failing test** — `tests/test_indicators.py`

```python
import pandas as pd
import pytest
from engine.indicators import compute_indicators

def _df(closes):
    return pd.DataFrame({
        "open": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [100.0] * len(closes),
    })

def test_rising_series_is_overbought_and_trending_up():
    f = compute_indicators(_df([100.0 + i for i in range(60)]))
    assert f["rsi"] > 70          # only gains -> RSI near 100
    assert f["macd"] > 0          # fast EMA above slow EMA
    assert f["ma_fast"] > f["ma_slow"]
    assert f["atr"] > 0
    assert f["price"] == 159.0    # last close

def test_falling_series_is_oversold():
    f = compute_indicators(_df([200.0 - i for i in range(60)]))
    assert f["rsi"] < 30
    assert f["macd"] < 0

def test_too_few_rows_raises():
    with pytest.raises(ValueError):
        compute_indicators(_df([100.0 + i for i in range(10)]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.indicators'`

- [ ] **Step 3: Write `engine/indicators.py`**

```python
import pandas as pd

MIN_ROWS = 50

# ponytail: indicators computed directly in pandas instead of pandas-ta.
# ~30 lines of standard formulas, fully tested, and avoids pandas-ta's
# numpy-version fragility. Upgrade path: swap to pandas-ta if more indicators
# are needed than is worth hand-rolling.


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def compute_indicators(df: pd.DataFrame) -> dict:
    if len(df) < MIN_ROWS:
        raise ValueError(f"need >= {MIN_ROWS} rows, got {len(df)}")
    close = df["close"]
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=9, adjust=False).mean()
    return {
        "price": float(close.iloc[-1]),
        "rsi": float(_rsi(close).iloc[-1]),
        "macd": float(macd.iloc[-1]),
        "macd_signal": float(signal.iloc[-1]),
        "ma_fast": float(close.rolling(20).mean().iloc[-1]),
        "ma_slow": float(close.rolling(50).mean().iloc[-1]),
        "atr": float(_atr(df).iloc[-1]),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_indicators.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/indicators.py tests/test_indicators.py
git commit -m "feat: hand-rolled RSI/MACD/MA/ATR indicators"
```

---

### Task 4: Risk gate (`broker.plan_order` + `stop_triggered`)

**Files:**
- Create: `engine/broker.py`
- Test: `tests/test_broker.py`

**Interfaces:**
- Consumes: `Decision`, `Position`, `RiskConfig` (Tasks 1–2).
- Produces: `plan_order(decision, position, cash, price, equity, risk) -> Order | None` (None = no trade); `stop_triggered(position, price) -> bool`. Buy notional is capped to `min(size*equity, max_position_pct*equity - current_position_value, cash)`; sell qty capped to held quantity; flat sell and sub-epsilon orders return None.

- [ ] **Step 1: Write the failing test** — `tests/test_broker.py`

```python
import pytest
from engine.models import Decision, Position
from engine.config import RiskConfig
from engine.broker import plan_order, stop_triggered

RISK = RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05)

def test_buy_capped_by_max_position_pct():
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=10000, price=10, equity=1000, risk=RISK)
    assert o.side == "buy"
    assert o.qty == pytest.approx(25.0)   # 0.25*1000=250 notional / 10

def test_buy_capped_by_cash():
    o = plan_order(Decision(action="buy", size=1.0),
                   Position("BTC/USDT"), cash=100, price=10, equity=1_000_000, risk=RISK)
    assert o.qty == pytest.approx(10.0)   # cash 100 / price 10

def test_buy_respects_existing_position_value():
    pos = Position("BTC/USDT", qty=20, avg_price=10, stop_price=9)
    # equity 1000 -> max position value 250; already holding 20*10=200 -> only 50 headroom
    o = plan_order(Decision(action="buy", size=1.0), pos, cash=10000, price=10, equity=1000, risk=RISK)
    assert o.qty == pytest.approx(5.0)

def test_sell_capped_to_holdings():
    pos = Position("BTC/USDT", qty=4, avg_price=10, stop_price=9)
    o = plan_order(Decision(action="sell", size=1.0), pos, cash=0, price=10, equity=40, risk=RISK)
    assert o.side == "sell" and o.qty == pytest.approx(4.0)

def test_sell_when_flat_is_none():
    assert plan_order(Decision(action="sell", size=1.0),
                      Position("BTC/USDT"), cash=0, price=10, equity=0, risk=RISK) is None

def test_hold_is_none():
    assert plan_order(Decision(action="hold"),
                      Position("BTC/USDT"), cash=100, price=10, equity=100, risk=RISK) is None

def test_stop_triggered():
    pos = Position("BTC/USDT", qty=1, avg_price=100, stop_price=95)
    assert stop_triggered(pos, 94) is True
    assert stop_triggered(pos, 96) is False
    assert stop_triggered(Position("BTC/USDT"), 1) is False  # flat
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.broker'`

- [ ] **Step 3: Write `engine/broker.py` (gate portion)**

```python
from engine.models import Decision, Position, Order

_EPS = 1e-6


def plan_order(decision: Decision, position: Position, cash: float,
               price: float, equity: float, risk) -> Order | None:
    """Turn an LLM decision into a clamped, executable order (or None).

    The gate is authoritative: buys are capped to the per-position limit AND
    available cash; sells are capped to held quantity. Spot long-only, so a
    sell never exceeds holdings and a buy never exceeds the cap.
    """
    if price <= 0:
        return None
    if decision.action == "buy":
        max_position_value = risk.max_position_pct * equity
        headroom = max(0.0, max_position_value - position.qty * price)
        notional = min(decision.size * equity, headroom, cash)
        qty = notional / price
        if qty * price < _EPS:
            return None
        return Order(side="buy", qty=qty, price=price)
    if decision.action == "sell":
        qty = min(decision.size * position.qty, position.qty)
        if qty <= _EPS:
            return None
        return Order(side="sell", qty=qty, price=price)
    return None


def stop_triggered(position: Position, price: float) -> bool:
    return position.qty > 0 and position.stop_price > 0 and price <= position.stop_price
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_broker.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/broker.py tests/test_broker.py
git commit -m "feat: risk gate (plan_order, stop_triggered)"
```

---

### Task 5: Paper broker fills (`broker.apply_fill`)

**Files:**
- Modify: `engine/broker.py` (append `apply_fill`)
- Test: `tests/test_broker.py` (append fill tests)

**Interfaces:**
- Consumes: `Order`, `Position` (Task 2).
- Produces: `apply_fill(order, position, cash, fee_pct, slippage_pct, stop_loss_pct, ts) -> (Position, float, Fill)`. Buy: effective price `price*(1+slippage)`, fee on notional, updates avg price + sets `stop_price = new_avg*(1-stop_loss_pct)`. Sell: effective price `price*(1-slippage)`; full exit resets the position to flat. Asserts a buy never spends more than `cash` and a sell never exceeds holdings.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_broker.py`

```python
from engine.broker import apply_fill

def test_buy_then_sell_roundtrip_profit_minus_costs():
    pos = Position("BTC/USDT")
    from engine.models import Order
    pos2, cash2, fill_b = apply_fill(Order("buy", 1.0, 100.0), pos, 1000.0,
                                     fee_pct=0.001, slippage_pct=0.0005,
                                     stop_loss_pct=0.05, ts="t1")
    assert cash2 < 1000.0
    assert pos2.qty == pytest.approx(1.0)
    assert pos2.stop_price == pytest.approx(pos2.avg_price * 0.95)
    pos3, cash3, fill_s = apply_fill(Order("sell", 1.0, 110.0), pos2, cash2,
                                     fee_pct=0.001, slippage_pct=0.0005,
                                     stop_loss_pct=0.05, ts="t2")
    assert pos3.qty == 0.0 and pos3.avg_price == 0.0   # flat after full exit
    assert 1000.0 < cash3 < 1010.0                     # profit on +10 move, minus costs

def test_buy_exceeding_cash_asserts():
    from engine.models import Order
    with pytest.raises(AssertionError):
        apply_fill(Order("buy", 100.0, 100.0), Position("BTC/USDT"), 50.0,
                   0.001, 0.0005, 0.05, "t")

def test_sell_exceeding_holdings_asserts():
    from engine.models import Order
    with pytest.raises(AssertionError):
        apply_fill(Order("sell", 5.0, 100.0), Position("BTC/USDT", qty=1.0),
                   0.0, 0.001, 0.0005, 0.05, "t")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_broker.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_fill'`

- [ ] **Step 3: Append `apply_fill` to `engine/broker.py`**

```python
from engine.models import Fill   # add to existing imports at top of file


def apply_fill(order: Order, position: Position, cash: float, fee_pct: float,
               slippage_pct: float, stop_loss_pct: float, ts: str):
    """Simulate a fill: returns (new_position, new_cash, fill_record)."""
    if order.side == "buy":
        eff = order.price * (1 + slippage_pct)
        notional = order.qty * eff
        fee = notional * fee_pct
        spend = notional + fee
        assert spend <= cash + _EPS, "buy exceeds cash (risk gate failed)"
        new_qty = position.qty + order.qty
        new_avg = (position.qty * position.avg_price + order.qty * eff) / new_qty
        new_pos = Position(position.symbol, new_qty, new_avg, new_avg * (1 - stop_loss_pct))
        return new_pos, cash - spend, Fill(position.symbol, "buy", order.qty, eff, fee, ts)

    # sell
    assert order.qty <= position.qty + _EPS, "sell exceeds holdings (risk gate failed)"
    eff = order.price * (1 - slippage_pct)
    notional = order.qty * eff
    fee = notional * fee_pct
    new_qty = position.qty - order.qty
    if new_qty <= _EPS:
        new_pos = Position(position.symbol, 0.0, 0.0, 0.0)
    else:
        new_pos = Position(position.symbol, new_qty, position.avg_price, position.stop_price)
    return new_pos, cash + (notional - fee), Fill(position.symbol, "sell", order.qty, eff, fee, ts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_broker.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/broker.py tests/test_broker.py
git commit -m "feat: paper broker fills with fees, slippage, stop-loss seeding"
```

---

### Task 6: State persistence (`state.py`)

**Files:**
- Create: `engine/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `Position`, `Fill` (Task 2).
- Produces: `State` dataclass (`cash:float`, `positions:dict[str,Position]`, `equity_history:list[dict]`); `load_state(data_dir, initial_capital, symbols) -> State` (creates fresh, flat positions for every symbol, if `state.json` absent); `save_state_atomic(state, data_dir)`; `append_trade(fill, data_dir)`; `equity(state, price_map) -> float` (uses `avg_price` for symbols missing from `price_map`); `acquire_lock(data_dir)` contextmanager (exits the process if already locked).

- [ ] **Step 1: Write the failing test** — `tests/test_state.py`

```python
from engine.state import load_state, save_state_atomic, append_trade, equity
from engine.models import Position, Fill

def test_fresh_state_creates_flat_positions(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT", "ETH/USDT"])
    assert st.cash == 10000.0
    assert set(st.positions) == {"BTC/USDT", "ETH/USDT"}
    assert st.positions["BTC/USDT"].qty == 0.0
    assert st.equity_history == []

def test_save_then_load_roundtrip(tmp_path):
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 8000.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=1000.0, stop_price=950.0)
    st.equity_history.append({"ts": "t1", "equity": 10000.0})
    save_state_atomic(st, str(tmp_path))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.cash == 8000.0
    assert st2.positions["BTC/USDT"].qty == 2.0
    assert st2.positions["BTC/USDT"].stop_price == 950.0
    assert st2.equity_history == [{"ts": "t1", "equity": 10000.0}]

def test_append_trade_writes_header_then_rows(tmp_path):
    append_trade(Fill("BTC/USDT", "buy", 1.0, 100.0, 0.1, "t1"), str(tmp_path))
    append_trade(Fill("BTC/USDT", "sell", 1.0, 110.0, 0.11, "t2"), str(tmp_path))
    lines = (tmp_path / "trades.csv").read_text().strip().splitlines()
    assert lines[0] == "ts,symbol,side,qty,price,fee"
    assert len(lines) == 3   # header + 2 rows

def test_equity_uses_avg_price_when_missing(tmp_path):
    st = load_state(str(tmp_path), 1000.0, ["BTC/USDT"])
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=2.0, avg_price=500.0)
    assert equity(st, {}) == 1000.0 + 2.0 * 500.0          # falls back to avg
    assert equity(st, {"BTC/USDT": 600.0}) == 1000.0 + 2.0 * 600.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.state'`

- [ ] **Step 3: Write `engine/state.py`**

```python
import csv
import fcntl
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field

from engine.models import Position, Fill

_TRADE_HEADER = ["ts", "symbol", "side", "qty", "price", "fee"]


@dataclass
class State:
    cash: float
    positions: dict
    equity_history: list = field(default_factory=list)


def _state_path(data_dir: str) -> str:
    return os.path.join(data_dir, "state.json")


def load_state(data_dir: str, initial_capital: float, symbols: list[str]) -> State:
    os.makedirs(data_dir, exist_ok=True)
    path = _state_path(data_dir)
    if not os.path.exists(path):
        return State(cash=initial_capital,
                     positions={s: Position(s) for s in symbols},
                     equity_history=[])
    with open(path) as f:
        raw = json.load(f)
    positions = {s: Position(**p) for s, p in raw["positions"].items()}
    for s in symbols:                       # ensure newly-added symbols exist
        positions.setdefault(s, Position(s))
    return State(cash=raw["cash"], positions=positions,
                 equity_history=raw.get("equity_history", []))


def save_state_atomic(state: State, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    payload = {
        "cash": state.cash,
        "positions": {s: vars(p) for s, p in state.positions.items()},
        "equity_history": state.equity_history,
    }
    path = _state_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)                   # atomic on POSIX


def append_trade(fill: Fill, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "trades.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(_TRADE_HEADER)
        w.writerow([fill.ts, fill.symbol, fill.side, fill.qty, fill.price, fill.fee])


def equity(state: State, price_map: dict) -> float:
    total = state.cash
    for s, p in state.positions.items():
        total += p.qty * price_map.get(s, p.avg_price)
    return total


@contextmanager
def acquire_lock(data_dir: str):
    os.makedirs(data_dir, exist_ok=True)
    lock_file = open(os.path.join(data_dir, "bot.lock"), "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another cycle is already running; exiting")
        sys.exit(0)
    try:
        yield
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_state.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/state.py tests/test_state.py
git commit -m "feat: atomic state persistence + trade log + file lock"
```

---

### Task 7: Market data (`market.py`)

**Files:**
- Create: `engine/market.py`
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: an exchange object exposing `fetch_ohlcv(symbol, timeframe, limit)` and `fetch_ticker(symbol)` (ccxt shape; faked in tests).
- Produces: `make_exchange(name) -> ccxt exchange`; `fetch_ohlcv_df(exchange, symbol, timeframe, limit=200) -> pd.DataFrame` (columns `open,high,low,close,volume`); `fetch_price(exchange, symbol) -> float` (ticker `last`).

- [ ] **Step 1: Write the failing test** — `tests/test_market.py`

```python
from engine.market import fetch_ohlcv_df, fetch_price

class FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe, limit):
        # ccxt returns [ts, open, high, low, close, volume]
        return [[i, 100 + i, 101 + i, 99 + i, 100 + i, 5.0] for i in range(limit)]
    def fetch_ticker(self, symbol):
        return {"last": 123.45}

def test_fetch_ohlcv_df_shape():
    df = fetch_ohlcv_df(FakeExchange(), "BTC/USDT", "15m", limit=60)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 60
    assert df["close"].iloc[-1] == 159

def test_fetch_price():
    assert fetch_price(FakeExchange(), "BTC/USDT") == 123.45
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.market'`

- [ ] **Step 3: Write `engine/market.py`**

```python
import ccxt
import pandas as pd


def make_exchange(name: str):
    return getattr(ccxt, name)({"enableRateLimit": True})


def fetch_ohlcv_df(exchange, symbol: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    rows = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_price(exchange, symbol: str) -> float:
    return float(exchange.fetch_ticker(symbol)["last"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/market.py tests/test_market.py
git commit -m "feat: ccxt market-data wrapper"
```

---

### Task 8: LLM decision (`llm.py`)

**Files:**
- Create: `engine/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `Decision` (Task 2), `LLMConfig` (Task 1), `Position`.
- Produces: `decide(features:dict, position:Position, cash:float, cfg:LLMConfig, client=None) -> Decision`. Builds a system+user prompt, calls `client.chat.completions.create(...)` (default client = `openai.OpenAI(base_url, api_key)`), extracts JSON, validates into `Decision`. **Any** exception or invalid output → `Decision(action="hold", reason="llm-fallback: ...")`. Sends `response_format={"type":"json_object"}` only when `cfg.json_mode`.

- [ ] **Step 1: Write the failing test** — `tests/test_llm.py`

```python
from engine.llm import decide
from engine.config import LLMConfig
from engine.models import Position

CFG = LLMConfig(base_url="x", api_key="x", model="m", json_mode=True)
FEATS = {"price": 100, "rsi": 28, "macd": 1, "macd_signal": 0,
         "ma_fast": 101, "ma_slow": 99, "atr": 2}

class _Msg:    # minimal openai response shape
    def __init__(self, content): self.message = type("M", (), {"content": content})
class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]
class FakeClient:
    def __init__(self, content=None, exc=None):
        self.content, self.exc = content, exc
        self.chat = type("C", (), {"completions": self})()
    def create(self, **kwargs):
        if self.exc: raise self.exc
        return _Resp(self.content)

def test_valid_json_returns_decision():
    c = FakeClient(content='{"action":"buy","size":0.5,"reason":"oversold","stop":95}')
    d = decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c)
    assert d.action == "buy" and d.size == 0.5 and d.stop == 95

def test_json_wrapped_in_text_is_extracted():
    c = FakeClient(content='Here is my call:\n{"action":"sell","size":1.0}\nDone.')
    d = decide(FEATS, Position("BTC/USDT", qty=1), 0, CFG, client=c)
    assert d.action == "sell"

def test_malformed_output_is_hold():
    c = FakeClient(content="I think you should buy a lot!")
    assert decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c).action == "hold"

def test_invalid_action_is_hold():
    c = FakeClient(content='{"action":"moon","size":1}')
    assert decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c).action == "hold"

def test_exception_is_hold():
    c = FakeClient(exc=RuntimeError("network down"))
    d = decide(FEATS, Position("BTC/USDT"), 10000, CFG, client=c)
    assert d.action == "hold" and "network down" in d.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.llm'`

- [ ] **Step 3: Write `engine/llm.py`**

```python
import json

from engine.models import Decision, Position

SYSTEM_PROMPT = (
    "You are a disciplined crypto spot trader. You may only go long or flat "
    "(no shorting). Given indicator values and the current position, decide ONE "
    "action. Respond with ONLY a JSON object, no prose, of the form: "
    '{"action": "buy"|"sell"|"hold", "size": <0..1>, "reason": "<short>", '
    '"stop": <price or null>}. "size" is the fraction of equity to deploy on a '
    "buy, or the fraction of the held position to sell. Be conservative; prefer "
    "hold when the signal is weak."
)


def _build_user(features: dict, position: Position, cash: float) -> str:
    return (
        f"Symbol: {position.symbol}\n"
        f"Indicators: {json.dumps(features)}\n"
        f"Position: qty={position.qty}, avg_price={position.avg_price}\n"
        f"Available cash: {cash}\n"
        "What is your decision?"
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError("no JSON object found")


def decide(features: dict, position: Position, cash: float, cfg, client=None) -> Decision:
    if client is None:
        from openai import OpenAI
        client = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key)
    kwargs = dict(
        model=cfg.model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user(features, position, cash)},
        ],
        temperature=0,
    )
    if cfg.json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    try:
        resp = client.chat.completions.create(**kwargs)
        data = _extract_json(resp.choices[0].message.content)
        return Decision(**data)
    except Exception as e:                      # fail-safe: any failure -> HOLD
        return Decision(action="hold", size=0.0, reason=f"llm-fallback: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/llm.py tests/test_llm.py
git commit -m "feat: OpenAI-compatible LLM decision with HOLD fail-safe"
```

---

### Task 9: Cycle orchestration (`bot.py`)

**Files:**
- Create: `engine/bot.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: every module above.
- Produces: `run_once(cfg=None, market=None, llm=None) -> None`. Acquires the lock, loads state, processes each symbol (fetch → indicators → stop-check-or-LLM → risk gate → fill → persist trade), appends an equity-history point, saves state atomically, prints a per-symbol summary. `market`/`llm` are injectable modules (duck-typed: `market.make_exchange/fetch_ohlcv_df/fetch_price`, `llm.decide`) so the cycle runs fully offline in tests. `__main__` calls `run_once()`.

- [ ] **Step 1: Write the failing test** — `tests/test_bot.py`

```python
import json
import pandas as pd
from engine import bot
from engine.config import Config, RiskConfig, LLMConfig
from engine.models import Decision, Position
from engine.state import load_state

def _cfg(tmp_path, symbols=("BTC/USDT",)):
    return Config(exchange="x", symbols=list(symbols), timeframe="15m",
                  paper_capital=10000.0, fee_pct=0.001, slippage_pct=0.0005,
                  data_dir=str(tmp_path),
                  risk=RiskConfig(max_position_pct=0.25, stop_loss_pct=0.05),
                  llm=LLMConfig(base_url="x", api_key="x", model="m", json_mode=True))

def _df():
    closes = [100.0 + i for i in range(60)]
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes,
                         "volume": [5.0] * 60})

class FakeMarket:
    def __init__(self, price=159.0, raise_for=()):
        self.price, self.raise_for = price, set(raise_for)
    def make_exchange(self, name): return object()
    def fetch_ohlcv_df(self, ex, sym, tf, limit=200):
        if sym in self.raise_for: raise RuntimeError("fetch failed")
        return _df()
    def fetch_price(self, ex, sym): return self.price

class FakeLLM:
    def __init__(self, decision): self.decision = decision
    def decide(self, features, position, cash, cfg, client=None): return self.decision

def test_buy_decision_updates_state_and_logs_trade(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), llm=FakeLLM(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.cash < 10000.0
    assert st.positions["BTC/USDT"].qty > 0
    assert len(st.equity_history) == 1
    trades = (tmp_path / "trades.csv").read_text().strip().splitlines()
    assert len(trades) == 2  # header + 1 buy

def test_hold_decision_makes_no_trade(tmp_path):
    cfg = _cfg(tmp_path)
    bot.run_once(cfg, market=FakeMarket(), llm=FakeLLM(Decision(action="hold")))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.cash == 10000.0
    assert not (tmp_path / "trades.csv").exists()

def test_fetch_error_skips_symbol_keeps_going(tmp_path):
    cfg = _cfg(tmp_path, symbols=("BTC/USDT", "ETH/USDT"))
    market = FakeMarket(raise_for=("BTC/USDT",))
    bot.run_once(cfg, market=market, llm=FakeLLM(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT", "ETH/USDT"])
    assert st.positions["BTC/USDT"].qty == 0      # skipped
    assert st.positions["ETH/USDT"].qty > 0       # processed

def test_stop_loss_forces_exit(tmp_path):
    cfg = _cfg(tmp_path)
    # seed a position whose stop (200) sits above the current price (159) -> must sell
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    st.cash = 0.0
    st.positions["BTC/USDT"] = Position("BTC/USDT", qty=1.0, avg_price=210.0, stop_price=200.0)
    from engine.state import save_state_atomic
    save_state_atomic(st, str(tmp_path))
    # LLM says hold, but the stop must override and exit
    bot.run_once(cfg, market=FakeMarket(price=159.0), llm=FakeLLM(Decision(action="hold")))
    st2 = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st2.positions["BTC/USDT"].qty == 0.0
    assert st2.cash > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.bot'`

- [ ] **Step 3: Write `engine/bot.py`**

```python
import logging
from datetime import datetime, timezone

from engine import broker, indicators, market as market_mod, llm as llm_mod, state as state_mod
from engine.config import load_config
from engine.models import Order

log = logging.getLogger("bot")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_once(cfg=None, market=None, llm=None) -> None:
    cfg = cfg or load_config()
    market = market or market_mod
    llm = llm or llm_mod

    with state_mod.acquire_lock(cfg.data_dir):
        st = state_mod.load_state(cfg.data_dir, cfg.paper_capital, cfg.symbols)
        exchange = market.make_exchange(cfg.exchange)
        prices: dict[str, float] = {}
        ts = _now()

        for sym in cfg.symbols:
            try:
                df = market.fetch_ohlcv_df(exchange, sym, cfg.timeframe)
                feats = indicators.compute_indicators(df)
                price = market.fetch_price(exchange, sym)
            except Exception as e:                  # one bad symbol never aborts the cycle
                log.warning("skip %s: %s", sym, e)
                print(f"[{sym}] SKIP ({e})")
                continue

            feats["price"] = price          # fill/stop use the live ticker, not the stale candle close
            prices[sym] = price
            pos = st.positions[sym]
            equity = state_mod.equity(st, prices)   # best-effort equity for sizing

            if broker.stop_triggered(pos, price):
                order, reason = Order("sell", pos.qty, price), "stop-loss"
            else:
                decision = llm.decide(feats, pos, st.cash, cfg.llm)
                order = broker.plan_order(decision, pos, st.cash, price, equity, cfg.risk)
                reason = decision.reason

            if order is None:
                print(f"[{sym}] HOLD @ {price:.2f} — {reason}")
                continue

            new_pos, new_cash, fill = broker.apply_fill(
                order, pos, st.cash, cfg.fee_pct, cfg.slippage_pct,
                cfg.risk.stop_loss_pct, ts)
            st.positions[sym] = new_pos
            st.cash = new_cash
            state_mod.append_trade(fill, cfg.data_dir)
            print(f"[{sym}] {order.side.upper()} {order.qty:.6f} @ {fill.price:.2f} — {reason}")

        total = state_mod.equity(st, prices)
        st.equity_history.append({"ts": ts, "equity": total})
        state_mod.save_state_atomic(st, cfg.data_dir)
        print(f"cash={st.cash:.2f} equity={total:.2f}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bot.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: all tests pass (config, models, indicators, broker, state, market, llm, bot).

- [ ] **Step 6: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat: run_once decision cycle (stop-loss override, per-symbol isolation, atomic persist)"
```

---

### Task 10: Run instructions + live smoke test

**Files:**
- Create: `README.md`

**Interfaces:** none (docs + operator workflow).

- [ ] **Step 1: Write `README.md`**

````markdown
# Crypto Paper-Trading Bot — Engine

AI-driven crypto **paper-trading** bot (simulated money). One cron cycle:
ccxt data → indicators → LLM decision → risk gate → simulated fill → `data/`.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your real MYHERMES_API_KEY in .env
```

## Run one cycle
```bash
set -a && source .env && set +a
python -m engine.bot
```
Prints each symbol's decision and the cash/equity summary. State lives in
`data/state.json`; trades in `data/trades.csv`.

## Schedule it (cadence = your choice)
```cron
*/15 * * * * cd /path/to/cryptotrading_ai && set -a && . ./.env && set +a && .venv/bin/python -m engine.bot >> data/bot.log 2>&1
```
Change the cron expression to change cadence — hourly, daily, etc.

## Config
Edit `engine/config.yaml` — symbols, capital, risk limits, and the LLM
provider/model. Default: MyHermes AI + `z-ai/glm-5.2`. Swap `base_url` +
`api_key_env` + `model` for OpenRouter or any OpenAI-compatible endpoint.

## Tests
```bash
python -m pytest -q
```
````

- [ ] **Step 2: Live smoke test (manual, real network + real LLM key)**

Run: `set -a && source .env && set +a && python -m engine.bot`
Expected: real prices printed for BTC/USDT and ETH/USDT, a decision per symbol,
`data/state.json` written, and a summary line. If the LLM key is wrong or the
endpoint is down, every symbol should print `HOLD … llm-fallback: …` and **no
trade** should occur (fail-safe verified live).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: run instructions + cron example"
```

---

## Self-Review

- **Spec coverage:** paper trading ✓ (no real orders anywhere) · indicators-in-code ✓ (Task 3) · LLM decision via OpenAI-compatible endpoint with default MyHermes/`z-ai/glm-5.2` ✓ (Tasks 1, 8) · risk gate authoritative ✓ (Task 4) · fail-safe HOLD ✓ (Tasks 8, 9) · per-symbol error isolation ✓ (Task 9) · atomic state + lock ✓ (Task 6) · stop-loss per cycle ✓ (Tasks 4, 9) · CCXT data layer ✓ (Task 7) · cron-driven config cadence ✓ (Task 10). Dashboard (Next.js) is the separate Plan 2 — out of scope here by design; the engine writes the `data/state.json` + `data/trades.csv` contract it will read.
- **Placeholder scan:** every code step contains complete, runnable code; no TBD/TODO.
- **Type consistency:** `Decision`/`Position`/`Order`/`Fill` defined once in `models.py` (Task 2) and imported everywhere; `plan_order`/`apply_fill`/`stop_triggered` signatures match between `broker.py` and `bot.py`; `equity`/`load_state`/`save_state_atomic`/`append_trade`/`acquire_lock` match between `state.py` and `bot.py`.
- **Deliberate deviations (noted):** indicators hand-rolled in pandas instead of `pandas-ta` (avoids numpy-version fragility); a few more files than the spec's "~5–6" (`models.py`, `config.py`, `market.py`, `state.py`) to isolate I/O and keep logic unit-testable. LLM `stop` field is logged/parsed but v1 uses the config `stop_loss_pct` as the authoritative stop (simplest correct behavior; LLM-driven stops are a v2 refinement).
