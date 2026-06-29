# Live Execution — Slice 2: Real Spot Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `mode: "live"` that places **real spot market orders** (long-only) with the exchange as the source of truth for cash/qty, gated by two independent switches and a kill file.

**Architecture:** `run_once` routes `mode: "live"` to a new self-contained `_run_live` (parallel to `_run_shadow`) only when armed (`LIVE_TRADING_ARMED=yes`); unarmed live falls back to shadow. `_run_live` checks `data/HALT` first, reads real cash/qty from the exchange, keeps `avg_price`/`stop_price` in a `data/live_meta.json` sidecar updated from real fills, runs the unchanged `broker.plan_order` gate, and places one real market order per actionable symbol via the single new `market.create_order`. `state.json` becomes a read-only dashboard mirror. Paper and shadow paths are untouched.

**Tech Stack:** Python 3.14 engine (pytest, ccxt). Electron/TypeScript dashboard (one type + chip; build + Playwright verified).

## Global Constraints

- **TDD always:** red → green per step.
- **`mode: "paper"` (default) and `mode: "shadow"` ⇒ byte-identical behavior** to today. The only shared change is `status.json` gaining a `halted` field (always `false` off the live path); no existing status test forbids it.
- **Two-switch arm:** live places orders ONLY when `cfg.mode == "live"` AND `os.environ.get("LIVE_TRADING_ARMED") == "yes"`. Missing either ⇒ `_run_shadow` (logs intent, places nothing).
- **Kill file:** `data/HALT` is checked FIRST inside `_run_live`; present ⇒ no execution, status written with `halted: true`, return.
- **Exchange-as-truth:** cash + position qty are re-read every cycle via `market.fetch_balance`. Only `avg_price`/`stop_price` are persisted locally (sidecar). `state.json` is a read-only mirror.
- **`create_order` is the single order-placement site.** It lives only in `market.create_order`, called only from `_run_live`. `grep -rn "create_order" engine/` after this slice returns exactly three lines: the `def`, the ccxt call inside it, and the one `market.create_order(...)` caller in `bot._run_live`.
- **Fail closed:** a balance-fetch error ⇒ no orders this cycle (status still written, cycle returns cleanly).
- **Spot, long-only.** No live shorting/leverage/funding/derivatives; no limit orders; no multi-quote; no partial-fill chasing.
- **Secrets are env-only.** Live reuses slice-1 `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` (now a **trade-enabled, withdrawal-disabled** key). Never commit or echo a secret. The `Config` cred fields are already `repr=False`.
- **No new dependencies** (ccxt already present).
- **Commit trailers** (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q`. Desktop: `cd desktop && npm test` / `npm run build`.
- Full design: `docs/superpowers/specs/2026-06-29-live-execution-real-spot-design.md`.

---

### Task 1: State — `live_meta.json` sidecar (load/save)

**Files:**
- Modify: `engine/state.py` (add `load_live_meta` + `save_live_meta`)
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `load_live_meta(data_dir) -> dict` — `{symbol: {"avg_price": float, "stop_price": float}}`; missing/corrupt file → `{}`.
  - `save_live_meta(meta: dict, data_dir) -> None` — atomic write to `data/live_meta.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
def test_live_meta_round_trips(tmp_path):
    from engine import state as state_mod
    meta = {"BTC/USDT": {"avg_price": 64000.0, "stop_price": 60800.0}}
    state_mod.save_live_meta(meta, str(tmp_path))
    assert state_mod.load_live_meta(str(tmp_path)) == meta

def test_live_meta_missing_file_is_empty(tmp_path):
    from engine import state as state_mod
    assert state_mod.load_live_meta(str(tmp_path)) == {}

def test_live_meta_corrupt_file_is_empty(tmp_path):
    from engine import state as state_mod
    (tmp_path / "live_meta.json").write_text("{not json")
    assert state_mod.load_live_meta(str(tmp_path)) == {}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_state.py -k live_meta -q`
Expected: FAIL — `load_live_meta`/`save_live_meta` not defined.

- [ ] **Step 3: Implement**

In `engine/state.py`, add after `write_status` (it mirrors that atomic-write pattern):

```python
def _live_meta_path(data_dir: str) -> str:
    return os.path.join(data_dir, "live_meta.json")


def load_live_meta(data_dir: str) -> dict:
    """Sidecar {symbol: {avg_price, stop_price}} for live mode; missing/corrupt -> {}."""
    path = _live_meta_path(data_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):     # corrupt sidecar -> rebuild from fills next entry
        return {}


def save_live_meta(meta: dict, data_dir: str) -> None:
    os.makedirs(data_dir, exist_ok=True)
    path = _live_meta_path(data_dir)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, path)                       # atomic on POSIX
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_state.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/state.py tests/test_state.py
git commit -m "feat: live_meta.json sidecar (avg/stop) load+save"
```

---

### Task 2: Market — live credentials + `create_order` (real market order + reconcile)

**Files:**
- Modify: `engine/market.py` (`make_exchange` loads creds for `live` too; add `create_order`)
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: `engine.models.Fill`.
- Produces:
  - `make_exchange(name, mode="paper", api_key="", secret="")` — now loads creds when `mode in ("shadow", "live")`.
  - `create_order(exchange, symbol, side, qty, ref_price, ts) -> Fill` — places a real **market** order and returns the reconciled real fill (filled qty, average price, fee). `ref_price` is the fallback average when the response lacks one. Re-polls once via `fetch_order` if the response is not yet filled.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_market.py`:

```python
from engine.models import Fill   # add near the top imports if not present


def test_make_exchange_live_loads_credentials():
    ex = market.make_exchange("binance", "live", "LKEY", "LSEC")
    assert ex.apiKey == "LKEY" and ex.secret == "LSEC"


class _FilledExchange:
    def __init__(self):
        self.calls = []
    def create_order(self, symbol, type, side, amount):
        self.calls.append((symbol, type, side, amount))
        return {"id": "1", "status": "closed", "filled": amount,
                "average": 64010.0, "fee": {"cost": 0.64, "currency": "USDT"}}


def test_create_order_reconciles_filled_market_order():
    ex = _FilledExchange()
    fill = market.create_order(ex, "BTC/USDT", "buy", 0.01, 64000.0, "T")
    assert ex.calls == [("BTC/USDT", "market", "buy", 0.01)]   # real MARKET order
    assert isinstance(fill, Fill)
    assert fill.qty == 0.01 and fill.price == 64010.0 and fill.fee == 0.64
    assert fill.symbol == "BTC/USDT" and fill.side == "buy" and fill.ts == "T"


class _AsyncExchange:
    """Returns 'open' with no fill detail, then a closed order on fetch_order."""
    def create_order(self, symbol, type, side, amount):
        return {"id": "9", "status": "open", "filled": 0.0}
    def fetch_order(self, oid, symbol):
        return {"id": oid, "status": "closed", "filled": 0.02, "average": 159.5, "fee": {"cost": 0.16}}


def test_create_order_repolls_when_not_filled():
    fill = market.create_order(_AsyncExchange(), "SOL/USDT", "buy", 0.02, 159.0, "T")
    assert fill.qty == 0.02 and fill.price == 159.5 and fill.fee == 0.16


class _NoAvgExchange:
    def create_order(self, symbol, type, side, amount):
        return {"id": "2", "status": "closed", "filled": amount}   # no average, no fee


def test_create_order_falls_back_to_ref_price_and_zero_fee():
    fill = market.create_order(_NoAvgExchange(), "BTC/USDT", "sell", 0.01, 63000.0, "T")
    assert fill.price == 63000.0 and fill.fee == 0.0   # ref_price fallback, fee defaults 0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_market.py -k "live or create_order" -q`
Expected: FAIL — `create_order` not defined / `make_exchange` doesn't load live creds.

- [ ] **Step 3: Implement**

In `engine/market.py`, add the `Fill` import at the top:

```python
from engine.models import Fill
```

Replace the `make_exchange` credential guard (`if mode == "shadow":`) with:

```python
    if mode in ("shadow", "live"):
        opts["apiKey"] = api_key
        opts["secret"] = secret
```

Add `create_order` at the end of `engine/market.py`:

```python
def create_order(exchange, symbol: str, side: str, qty: float, ref_price: float, ts: str) -> Fill:
    """Place a REAL spot market order; return the reconciled real fill.

    The ONLY order-placement call in the engine. Prefers the response's
    filled/average/fee; re-polls once via fetch_order if not yet filled;
    falls back to ref_price for a missing average and 0.0 for a missing fee.
    """
    o = exchange.create_order(symbol, "market", side, qty)
    filled = float(o.get("filled") or 0.0)
    if o.get("status") != "closed" or filled <= 0:
        # ponytail: single re-poll, no chase loop; an under-read remainder
        # self-heals next cycle (exchange = truth for balances).
        try:
            o = exchange.fetch_order(o.get("id"), symbol) or o
            filled = float(o.get("filled") or filled or 0.0)
        except Exception:
            pass
    avg = float(o.get("average") or o.get("price") or ref_price)
    fee = float((o.get("fee") or {}).get("cost") or 0.0)
    return Fill(symbol, side, filled, avg, fee, ts)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_market.py -q`
Expected: PASS (new + existing; the 1-arg paper `make_exchange("binance")` is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/market.py tests/test_market.py
git commit -m "feat: market.create_order (real spot market order + fill reconcile) + live creds"
```

---

### Task 3: Market — `clamp_to_market` (precision + min-notional guard)

**Files:**
- Modify: `engine/market.py` (add `clamp_to_market`)
- Test: `tests/test_market.py`

**Interfaces:**
- Produces: `clamp_to_market(exchange, symbol, qty, price) -> float` — rounds `qty` to the market's amount precision; returns `0.0` if below the market's min amount or min cost; passes `qty` through unchanged when market limits are unavailable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_market.py`:

```python
class _LimitsExchange:
    markets = {"BTC/USDT": {"limits": {"amount": {"min": 0.001}, "cost": {"min": 10.0}}}}
    def amount_to_precision(self, symbol, qty):
        return f"{qty:.4f}"                       # 4-dp precision


def test_clamp_rounds_to_precision():
    assert market.clamp_to_market(_LimitsExchange(), "BTC/USDT", 0.0123456, 64000.0) == 0.0123


def test_clamp_below_min_amount_returns_zero():
    assert market.clamp_to_market(_LimitsExchange(), "BTC/USDT", 0.0005, 64000.0) == 0.0


def test_clamp_below_min_cost_returns_zero():
    # 0.0001 BTC * 64000 = 6.4 < 10.0 min cost
    assert market.clamp_to_market(_LimitsExchange(), "BTC/USDT", 0.0001, 64000.0) == 0.0


def test_clamp_unknown_market_passes_through():
    class _Bare:
        markets = {}
        def load_markets(self): return {}
    assert market.clamp_to_market(_Bare(), "BTC/USDT", 0.5, 100.0) == 0.5
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_market.py -k clamp -q`
Expected: FAIL — `clamp_to_market` not defined.

- [ ] **Step 3: Implement**

Add `clamp_to_market` to `engine/market.py`:

```python
def clamp_to_market(exchange, symbol: str, qty: float, price: float) -> float:
    """Round qty to the market's amount precision; 0.0 if below min amount/cost.

    Pass qty through unchanged when the exchange exposes no usable limits
    (ponytail: best-effort — the gate already bounds qty; a real venue has limits).
    """
    try:
        markets = getattr(exchange, "markets", None) or exchange.load_markets()
    except Exception:
        return qty
    m = (markets or {}).get(symbol)
    if not m:
        return qty
    try:
        adj = float(exchange.amount_to_precision(symbol, qty))
    except Exception:
        adj = qty
    limits = m.get("limits") or {}
    min_amt = (limits.get("amount") or {}).get("min")
    min_cost = (limits.get("cost") or {}).get("min")
    if min_amt is not None and adj < min_amt:
        return 0.0
    if min_cost is not None and adj * price < min_cost:
        return 0.0
    return adj
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_market.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/market.py tests/test_market.py
git commit -m "feat: clamp_to_market — exchange precision + min-notional guard"
```

---

### Task 4: Bot — `_run_live` + routing + `halted` status (the safety core)

**Files:**
- Modify: `engine/bot.py` (`import os`; `_status_payload` gains `halted`; add `_live_armed`, `_run_live`, `_update_meta`, `_write_live_mirror`; route `mode == "live"`)
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `state.load_live_meta`/`save_live_meta` (Task 1); `market.make_exchange(name, mode, key, secret)`/`fetch_balance`/`create_order`/`clamp_to_market` (Tasks 2–3); `broker.force_close`/`plan_order`; `state.append_trade`/`append_decision`/`save_state_atomic`/`load_state`/`write_status`.
- Produces:
  - `_live_armed() -> bool` — `os.environ.get("LIVE_TRADING_ARMED") == "yes"`.
  - `_status_payload(cfg, ts, funding_accrued, last_funding_ts, halted=False)` — adds top-level `"halted"`.
  - `_run_live(cfg, market, strategy) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py` (reuses the existing `_cfg`, `_df`, `_strat`, `_json`, `FakeMarket`, `load_state`, `Decision` helpers):

```python
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
        from engine.models import Fill
        return Fill(sym, side, qty, ref_price, qty * ref_price * 0.001, ts)


def test_live_armed_places_real_order(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert len(mk.orders) == 1 and mk.orders[0][1] == "buy"       # a REAL order placed
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["action"] == "buy" and rec["executed"] is True
    assert (tmp_path / "trades.csv").exists()                     # real fill recorded
    meta = _json.loads((tmp_path / "live_meta.json").read_text())
    assert meta["BTC/USDT"]["avg_price"] > 0                      # sidecar updated from fill
    status = _json.loads((tmp_path / "status.json").read_text())
    assert status["mode"] == "live" and status["halted"] is False


def test_live_unarmed_falls_back_to_shadow(tmp_path, monkeypatch):
    monkeypatch.delenv("LIVE_TRADING_ARMED", raising=False)
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # NO real order
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["executed"] is False and rec["reason"].startswith("[shadow]")
    assert not (tmp_path / "trades.csv").exists()


def test_live_halt_file_blocks_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    (tmp_path / "HALT").write_text("")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    mk = _LiveMarket()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # halted before any order
    assert not (tmp_path / "trades.csv").exists()
    status = _json.loads((tmp_path / "status.json").read_text())
    assert status["halted"] is True


def test_live_balance_failure_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    class _FailBal(_LiveMarket):
        def fetch_balance(self, ex, symbols): raise RuntimeError("auth failed")
    mk = _FailBal()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []                                        # no balance -> no order
    assert (tmp_path / "status.json").exists()                    # cycle survived


def test_live_below_min_notional_skips(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    class _ClampZero(_LiveMarket):
        def clamp_to_market(self, ex, sym, qty, price): return 0.0
    mk = _ClampZero()
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="buy", size=1.0)))
    assert mk.orders == []
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["executed"] is False and "min notional" in rec["reason"]


def test_live_stop_loss_sells_to_flat(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ARMED", "yes")
    cfg = _cfg(tmp_path); cfg.mode = "live"
    # seed a held long with a stop ABOVE the current price -> stop fires
    (tmp_path / "live_meta.json").write_text(
        _json.dumps({"BTC/USDT": {"avg_price": 200.0, "stop_price": 190.0}}))
    mk = _LiveMarket(qty={"BTC/USDT": 0.5}, price=159.0)          # price 159 <= stop 190
    bot.run_once(cfg, market=mk, strategy=_strat(Decision(action="hold")))
    assert len(mk.orders) == 1 and mk.orders[0] == ("BTC/USDT", "sell", 0.5)
    meta = _json.loads((tmp_path / "live_meta.json").read_text())
    assert "BTC/USDT" not in meta                                 # sidecar cleared on close
```

Note: `_cfg` builds a single-symbol `BTC/USDT` config (matching the existing shadow tests). If `_cfg` uses a different symbol, adjust the symbol keys above to match it.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bot.py -k live -q`
Expected: FAIL — `mode == "live"` not routed / `_run_live` not defined / `status.json` has no `halted`.

- [ ] **Step 3: Implement**

In `engine/bot.py`, add `import os` to the imports.

Add `halted` to `_status_payload` (signature + dict):

```python
def _status_payload(cfg, ts, funding_accrued, last_funding_ts, halted=False):
    return {
        "ts": ts,
        "mode": cfg.mode,
        "halted": halted,
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

(The existing paper/shadow `_status_payload(...)` call sites pass 4 args; `halted` defaults `False` — no change needed there.)

In `run_once`, REPLACE the existing shadow branch:

```python
    if cfg.mode == "shadow":
        _run_shadow(cfg, market, strategy)
        return
```

with the live + shadow routing:

```python
    if cfg.mode == "live":
        if _live_armed():
            _run_live(cfg, market, strategy)
        else:
            log.warning("mode=live but LIVE_TRADING_ARMED != 'yes' -> shadow (no orders placed)")
            _run_shadow(cfg, market, strategy)
        return
    if cfg.mode == "shadow":
        _run_shadow(cfg, market, strategy)
        return
```

Add these functions to `engine/bot.py` (after `_run_shadow`):

```python
def _live_armed() -> bool:
    """Second, independent switch: env must explicitly arm live trading."""
    return os.environ.get("LIVE_TRADING_ARMED") == "yes"


def _update_meta(meta: dict, sym: str, pos, side: str, fill, stop_loss_pct: float) -> dict:
    """Recompute the sidecar avg/stop from a real fill (long-only spot)."""
    if side == "buy":                                  # open/extend long
        new_qty = pos.qty + fill.qty
        new_avg = ((pos.qty * pos.avg_price + fill.qty * fill.price) / new_qty
                   if new_qty > 0 else fill.price)
        meta[sym] = {"avg_price": new_avg, "stop_price": new_avg * (1 - stop_loss_pct)}
    else:                                              # sell reduces a long
        if pos.qty - fill.qty <= 1e-8:                 # closed to flat
            meta.pop(sym, None)
        else:                                          # partial reduce -> avg/stop unchanged
            meta[sym] = {"avg_price": pos.avg_price, "stop_price": pos.stop_price}
    return meta


def _write_live_mirror(cfg, ts, cash, qty_by, meta, prices) -> None:
    """Read-only state.json mirror so the dashboard shows live positions.

    ponytail: reflects START-of-cycle balances (one-cycle lag after a fill);
    next cycle re-reads the real balance and corrects it. Re-fetch at end if
    instant post-fill display ever matters.
    """
    st = state_mod.load_state(cfg.data_dir, 0.0, cfg.symbols)   # reuse for equity_history
    st.cash = cash
    for sym in cfg.symbols:
        m = meta.get(sym, {})
        st.positions[sym] = Position(sym, qty=qty_by.get(sym, 0.0),
                                     avg_price=m.get("avg_price", 0.0),
                                     stop_price=m.get("stop_price", 0.0))
    if prices:
        total = cash + sum(qty_by.get(s, 0.0) * prices.get(s, 0.0) for s in cfg.symbols)
        st.equity_history.append({"ts": ts, "equity": total})
    state_mod.save_state_atomic(st, cfg.data_dir, cfg.risk.maintenance_margin_pct)


def _run_live(cfg, market, strategy) -> None:
    """Place REAL spot market orders. Exchange = truth for cash/qty; sidecar = avg/stop."""
    with state_mod.acquire_lock(cfg.data_dir):
        ts = _now()
        if os.path.exists(os.path.join(cfg.data_dir, "HALT")):
            log.warning("data/HALT present -> no live execution this cycle")
            print("[LIVE] HALTED (data/HALT present) — no orders")
            _safe_write_status(cfg, ts, halted=True)
            return

        print(f"[LIVE] placing real orders on {cfg.exchange}")
        exchange = market.make_exchange(cfg.exchange, "live",
                                        cfg.exchange_api_key, cfg.exchange_secret)
        if cfg.risk.allow_short is None:
            cfg.risk.allow_short = market_mod.supports_short(exchange)
        bd = (sentiment_mod.breakdown(cfg.symbols, cfg) if cfg.sentiment.enabled else {})

        try:
            cash, qty_by = market.fetch_balance(exchange, cfg.symbols)
        except Exception as e:                          # fail closed: no balance -> no orders
            log.warning("live: balance fetch failed: %s", e)
            print(f"[LIVE] balance unavailable ({e}); no orders this cycle")
            _safe_write_status(cfg, ts, halted=False)
            return

        meta = state_mod.load_live_meta(cfg.data_dir)
        prices: dict[str, float] = {}
        for sym in cfg.symbols:
            try:
                df = market.fetch_ohlcv_df(exchange, sym, cfg.timeframe)
                feats = indicators.compute_indicators(df)
                price = market.fetch_price(exchange, sym)
                if price <= 0:
                    raise ValueError(f"non-positive price: {price}")
            except Exception as e:
                log.warning("skip %s: %s", sym, e)
                print(f"[{sym}] SKIP ({e})")
                continue

            prices[sym] = price
            m = meta.get(sym, {})
            pos = Position(sym, qty=qty_by.get(sym, 0.0),
                           avg_price=m.get("avg_price", 0.0),
                           stop_price=m.get("stop_price", 0.0))
            feats["price"] = price
            feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)
            feats["allow_short"] = bool(cfg.risk.allow_short)
            equity = cash + sum(qty_by.get(s, 0.0) * prices.get(s, 0.0) for s in cfg.symbols)

            reason = broker.force_close(pos, price, cfg.risk)   # spot -> only "stop-loss" can fire
            if reason:
                order = Order("sell", pos.qty, price) if pos.qty > 0 else Order("buy", -pos.qty, price)
            else:
                decision = strategy(feats, pos, cash, cfg)
                order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)
                reason = decision.reason

            if order is None:
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": "hold", "reason": reason,
                     "price": price, "executed": False}, cfg.data_dir)
                print(f"[LIVE][{sym}] HOLD @ {price:.2f} — {reason}")
                continue

            qty = market.clamp_to_market(exchange, sym, order.qty, price)
            if qty <= 0:
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": order.side,
                     "reason": f"below min notional — {reason}", "price": price,
                     "executed": False}, cfg.data_dir)
                print(f"[LIVE][{sym}] SKIP {order.side} {order.qty:.8f} — below min notional")
                continue

            try:
                fill = market.create_order(exchange, sym, order.side, qty, price, ts)
            except Exception as e:                       # rejected/insufficient/down -> skip symbol
                log.warning("live: order failed %s %s: %s", sym, order.side, e)
                state_mod.append_decision(
                    {"ts": ts, "symbol": sym, "action": order.side,
                     "reason": f"order failed: {e}", "price": price, "executed": False}, cfg.data_dir)
                print(f"[LIVE][{sym}] ORDER FAILED ({e})")
                continue

            state_mod.append_trade(fill, cfg.data_dir)
            state_mod.append_decision(
                {"ts": ts, "symbol": sym, "action": order.side, "reason": reason,
                 "price": fill.price, "executed": True}, cfg.data_dir)
            meta = _update_meta(meta, sym, pos, order.side, fill, cfg.risk.stop_loss_pct)
            print(f"[LIVE][{sym}] {order.side.upper()} {fill.qty:.8f} @ {fill.price:.2f} — {reason}")

        state_mod.save_live_meta(meta, cfg.data_dir)
        _write_live_mirror(cfg, ts, cash, qty_by, meta, prices)
        _safe_write_status(cfg, ts, halted=False)


def _safe_write_status(cfg, ts, halted) -> None:
    try:                                     # advisory: a status write error never aborts the cycle
        state_mod.write_status(_status_payload(cfg, ts, 0.0, None, halted=halted), cfg.data_dir)
    except Exception as e:
        log.warning("status snapshot write failed: %s", e)
```

- [ ] **Step 4: Run the engine suite**

Run: `python -m pytest -q`
Expected: PASS — new live tests + every existing test (paper/shadow paths unchanged; `status.json` now also carries `halted`, which no existing test forbids).

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat: live-mode bot — real spot orders, two-switch arm, HALT kill file, exchange-as-truth"
```

---

### Task 5: Dashboard — `halted` in status + HALTED indicator

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`Status` gains `halted?`)
- Modify: `desktop/src/renderer/src/components/StatusStrip.tsx` (HALTED chip when halted)

**Interfaces:**
- Consumes: `status.json`'s new `halted` field (Task 4).

- [ ] **Step 1: Add the type field**

In `desktop/src/lib/parse.ts`, extend the `Status` type with `halted`:

```typescript
export type Status = { ts: string; strategy: string; exchange: string; mode?: string; halted?: boolean;
                       risk: RiskStatus; funding: FundingStatus };
```

- [ ] **Step 2: Show a HALTED chip**

In `desktop/src/renderer/src/components/StatusStrip.tsx`, insert a HALTED chip right after the Mode chip when `status.halted` is true. Replace the `chips` array literal with:

```tsx
  const chips: [string, string][] = [
    ["Mode", (status.mode ?? "paper").toUpperCase()],
    ...(status.halted ? [["Halted", "YES"] as [string, string]] : []),
    ["Strategy", status.strategy],
    ["Exchange", status.exchange],
    ["Leverage", leverageMode(r.leverage)],
    ["Shorting", shortingLabel(r.allow_short)],
    ["Funding", fundingSummary(status)],
    ["Accrued", accruedLabel(status.funding.accrued)],
    ["Max position", `${(r.max_position_pct * 100).toFixed(0)}%`],
    ["Stop", `${(r.stop_loss_pct * 100).toFixed(0)}%`],
  ];
```

- [ ] **Step 3: Build + test**

Run: `cd desktop && npm test && npm run build`
Expected: vitest PASS (optional `halted?` doesn't break existing Status fixtures); build exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/renderer/src/components/StatusStrip.tsx
git commit -m "feat: dashboard HALTED indicator (kill-file active)"
```

---

### Task 6: Docs + config + final verification

**Files:**
- Modify: `engine/config.yaml` (document `mode: live` + the arm env var + kill file)
- Modify: `README.md` (Live execution section)
- Test: full suites + the `create_order` audit + Playwright

- [ ] **Step 1: Document config**

In `engine/config.yaml`, update the `mode` comment line to include `live`:

```yaml
mode: paper                       # paper (simulated) | shadow (real read-only) | live (real orders)
# Live also requires env LIVE_TRADING_ARMED=yes (second switch); touch data/HALT to stop instantly.
```

- [ ] **Step 2: Update README**

Add a `## Live execution (real orders)` section to `README.md` after the Shadow mode section (before Tests):

```markdown
## Live execution (real orders)

Set `mode: live` **and** export `LIVE_TRADING_ARMED=yes` to place **real spot market orders**
(long-only). Both switches are required — `mode: live` alone (or a stale committed config) falls
back to shadow and places nothing. Use a **trade-enabled, withdrawal-disabled** API key in `.env`
(`EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`).

The exchange is the source of truth: each cycle re-reads your real cash + balances, so a crash, a
partial fill, or a manual trade never desyncs the bot. Entry price and stop-loss (which the exchange
doesn't store) live in `data/live_meta.json`; `data/state.json` is a read-only mirror for the
dashboard. Orders are sized by the same risk gate as paper, rounded to the exchange's precision, and
skipped if below its minimum notional.

**Kill switch:** `touch data/HALT` stops all execution instantly (the dashboard shows `HALTED`);
`rm data/HALT` resumes. Progression: `paper` (simulated) → `shadow` (real reads, zero execution) →
`live` (real orders). `create_order` exists in exactly one place (`market.create_order`), reachable
only when live, armed, and not halted.
```

- [ ] **Step 3: Full engine + desktop suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest green; build exit 0.

- [ ] **Step 4: Audit — `create_order` is the single gated site**

Run: `grep -rn "create_order" engine/`
Expected: exactly three lines — `def create_order` in `market.py`, the `exchange.create_order(...)` call inside it, and the one `market.create_order(...)` caller in `bot.py` `_run_live`. Confirm no other module calls it and the caller sits inside the live-armed path.

- [ ] **Step 5: Playwright visual verification**

Build the renderer, serve a harness with a `status` whose `mode` is `"live"` and `halted` is `true`, screenshot the Status strip at 1280 / 768 / 375. Confirm `MODE: LIVE` and the `HALTED: YES` chip render; confirm a `halted: false` snapshot hides the HALTED chip. Clean up harness artifacts after.

- [ ] **Step 6: Commit**

```bash
git add engine/config.yaml README.md
git commit -m "docs: document live execution (two-switch arm, kill file, trade-enabled key)"
```

---

## Self-Review

**Spec coverage:**
- Routing (`mode: live` + armed → `_run_live`; unarmed → shadow; HALT first) → Task 4 ✓
- Two-switch arm (`mode: live` + `LIVE_TRADING_ARMED=yes`) → Task 4 (`_live_armed` + routing) ✓
- Kill file (`data/HALT`, status `halted`) → Task 4 (`_run_live` check) + Task 5 (chip) ✓
- Exchange-as-truth + sidecar (`live_meta.json`) → Task 1 (sidecar) + Task 4 (`fetch_balance` truth, `_update_meta`, `_write_live_mirror` read-only state.json mirror) ✓
- Real market order + reconcile (`create_order`) → Task 2 ✓
- Precision / min-notional guard → Task 3 + Task 4 (skip on qty ≤ 0) ✓
- Fail closed on balance error → Task 4 ✓
- Live credentials (reuse slice-1 env) → Task 2 (`make_exchange` loads live creds) ✓
- Banner / never silent → Task 4 (`print("[LIVE] placing real orders ...")`) ✓
- `create_order` single gated site audit → Task 6 ✓
- Dashboard HALTED + LIVE → Task 5 (chip) + Task 6 (Playwright) ✓
- README + config docs + trade-enabled key warning → Task 6 ✓
- Paper/shadow byte-identical → Tasks 4 (default `halted=False`, routing leaves both paths intact) ✓

**Placeholder scan:** none — every code step shows full code and exact insertion points. The `_cfg` symbol note in Task 4 instructs adjusting test keys to match the existing helper rather than leaving a blank.

**Type/signature consistency:**
- `load_live_meta(data_dir) -> dict` / `save_live_meta(meta, data_dir)` — Task 1 defines, Task 4 consumes ✓
- `create_order(exchange, symbol, side, qty, ref_price, ts) -> Fill` — Task 2 defines, Task 4 calls with `(exchange, sym, order.side, qty, price, ts)` ✓
- `clamp_to_market(exchange, symbol, qty, price) -> float` — Task 3 defines, Task 4 calls with `(exchange, sym, order.qty, price)` ✓
- `_status_payload(cfg, ts, funding_accrued, last_funding_ts, halted=False)` — Task 4 adds `halted`; paper/shadow 4-arg call sites unaffected (default) ✓
- `make_exchange(name, mode, api_key, secret)` — Task 2 loads creds for `live`; Task 4 calls with `"live"` ✓
- `Status.halted?` — Task 5 defines, the chip consumes ✓
```
