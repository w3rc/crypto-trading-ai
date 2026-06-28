# Live Execution — Slice 1: Shadow Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `mode: "shadow"` that runs the bot against the REAL exchange account read-only — fetch real balance + price, compute the order it *would* place, log it — executing nothing and mutating no money.

**Architecture:** A new `mode` config + read-only authenticated exchange + `market.fetch_balance`. The bot gets an early `mode == "shadow"` branch into a self-contained `_run_shadow` that sources cash/qty from the real account, runs the same risk gate, and logs the intended order instead of filling it. The paper path is untouched.

**Tech Stack:** Python 3.14 engine (pytest, ccxt). Electron/TypeScript dashboard (one type + chip; build + Playwright verified).

## Global Constraints

- **TDD always:** red → green per step.
- **`mode: "paper"` (default) ⇒ byte-identical trading behavior** — public client, simulated fills, `state.json` truth. The paper `make_exchange(cfg.exchange)` call stays 1-arg/unchanged.
- **Shadow places NO orders and mutates NO money.** `create_order`/`cancel_order`/any write call must NOT be added anywhere in this slice — auditable by grep. Shadow's only exchange calls are `fetch_ohlcv` / `fetch_ticker` / `fetch_balance`; it never calls `apply_fill` / `append_trade` / `save_state_atomic`.
- **The risk gate (`plan_order`) is unchanged** — shadow runs the same gate; it only changes the *source* of cash/qty (real balance) and the *sink* of the order (a log).
- **Secrets are env-only.** API key/secret resolved from env vars named in config (default `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`), like the existing `MYHERMES_API_KEY`. Never commit a secret; never echo one.
- Spot, long-only. No live derivatives, no `create_order`, no exchange-as-truth avg/stop, no kill switch (those are slice 2).
- **No new dependencies** (ccxt already present).
- **Commit trailers** (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FTSWWZ199XjWUfpDycsDJH
  ```
- Engine tests: `python -m pytest -q`. Desktop: `cd desktop && npm test` / `npm run build`.
- Full design: `docs/superpowers/specs/2026-06-28-live-execution-shadow-design.md`.

---

### Task 1: Config — `mode` + credential resolution

**Files:**
- Modify: `engine/config.py` (`Config` + `load_config`)
- Modify: `engine/config.yaml` (document `mode` + env var names)
- Modify: `.env.example` (document the two env vars)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Config(..., mode: str = "paper", exchange_api_key: str = "", exchange_secret: str = "")`. `load_config` reads `mode` and resolves the two secrets from the env vars named by `exchange_api_key_env` / `exchange_secret_env` (defaults `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_mode_defaults_paper(monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    assert load_config("engine/config.yaml").mode == "paper"

def test_mode_and_credentials_load(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    monkeypatch.setenv("EXCHANGE_API_KEY", "pubkey")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "secret")
    p = tmp_path / "c.yaml"
    p.write_text(
        "exchange: binance\nsymbols: [BTC/USDT]\ntimeframe: 15m\n"
        "paper_capital: 1000\nfee_pct: 0.001\nslippage_pct: 0.0005\ndata_dir: data\n"
        "mode: shadow\n"
        "risk:\n  max_position_pct: 0.25\n  stop_loss_pct: 0.05\n"
        "llm:\n  base_url: x\n  api_key_env: MYHERMES_API_KEY\n  model: m\n  json_mode: true\n"
    )
    cfg = load_config(str(p))
    assert cfg.mode == "shadow"
    assert cfg.exchange_api_key == "pubkey"
    assert cfg.exchange_secret == "secret"

def test_credentials_absent_are_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MYHERMES_API_KEY", "k")
    monkeypatch.delenv("EXCHANGE_API_KEY", raising=False)
    cfg = load_config("engine/config.yaml")
    assert cfg.exchange_api_key == ""   # absent env -> "" (paper never needs it)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_config.py -k "mode or credential" -q`
Expected: FAIL — `Config` has no `mode`.

- [ ] **Step 3: Implement**

In `engine/config.py`, extend `Config` (append after `sentiment`):

```python
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
    strategy: str = "hybrid"
    rules: RulesConfig = field(default_factory=RulesConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    mode: str = "paper"
    exchange_api_key: str = ""
    exchange_secret: str = ""
```

In `engine/config.py` `load_config`, add to the `Config(...)` construction (after the `sentiment=...` block, before the closing `)`):

```python
        mode=raw.get("mode", "paper"),
        exchange_api_key=os.environ.get(raw.get("exchange_api_key_env", "EXCHANGE_API_KEY"), ""),
        exchange_secret=os.environ.get(raw.get("exchange_secret_env", "EXCHANGE_API_SECRET"), ""),
```

In `engine/config.yaml`, add near the top (after `data_dir: data`):

```yaml
mode: paper                       # paper (simulated) | shadow (real read-only dry-run)
# exchange_api_key_env: EXCHANGE_API_KEY      # env var holding a READ-ONLY exchange key (shadow)
# exchange_secret_env: EXCHANGE_API_SECRET
```

In `.env.example`, append (read the file first; add below the existing keys):

```bash
# Exchange credentials for shadow mode (use a READ-ONLY / no-trade API key)
EXCHANGE_API_KEY=
EXCHANGE_API_SECRET=
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_config.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add engine/config.py engine/config.yaml .env.example tests/test_config.py
git commit -m "feat: mode (paper|shadow) + exchange credential resolution"
```

---

### Task 2: Market — authenticated client + `fetch_balance`

**Files:**
- Modify: `engine/market.py` (`make_exchange` gains `mode`/creds; `+ fetch_balance`)
- Test: `tests/test_market.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `make_exchange(name, mode="paper", api_key="", secret="")` — `paper` → public client (1-arg call unchanged); `shadow` → client with `apiKey`/`secret`.
  - `fetch_balance(exchange, symbols) -> tuple[float, dict[str, float]]` — `(free quote, {symbol: free base})`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_market.py`:

```python
def test_make_exchange_shadow_loads_credentials():
    ex = market.make_exchange("binance", "shadow", "KEY123", "SECRET456")
    assert ex.apiKey == "KEY123"
    assert ex.secret == "SECRET456"

def test_make_exchange_paper_has_no_credentials():
    ex = market.make_exchange("binance")        # 1-arg paper call unchanged
    assert not ex.apiKey                        # "" / None -> falsy

class BalanceExchange:
    def fetch_balance(self):
        return {"USDT": {"free": 5000.0, "used": 0.0, "total": 5000.0},
                "BTC": {"free": 0.25, "used": 0.0, "total": 0.25}}

def test_fetch_balance_maps_quote_and_base():
    cash, qty = market.fetch_balance(BalanceExchange(), ["BTC/USDT", "ETH/USDT"])
    assert cash == 5000.0                        # free USDT (shared quote)
    assert qty["BTC/USDT"] == 0.25
    assert qty["ETH/USDT"] == 0.0                # no ETH balance -> 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_market.py -k "shadow or credentials or balance" -q`
Expected: FAIL — `make_exchange` takes 1 arg / `fetch_balance` not defined.

- [ ] **Step 3: Implement**

In `engine/market.py`, replace `make_exchange` and add `fetch_balance`:

```python
def make_exchange(name: str, mode: str = "paper", api_key: str = "", secret: str = ""):
    opts = {"enableRateLimit": True}
    if mode == "shadow":
        opts["apiKey"] = api_key
        opts["secret"] = secret
    return getattr(ccxt, name)(opts)


def fetch_balance(exchange, symbols: list[str]) -> tuple[float, dict[str, float]]:
    """Real account balance, read-only: (free quote, {symbol: free base})."""
    bal = exchange.fetch_balance()

    def free(asset: str) -> float:
        return float((bal.get(asset) or {}).get("free", 0.0) or 0.0)

    quote = symbols[0].split("/")[1] if symbols else "USDT"
    # ponytail: assumes one shared quote across symbols (USDT); multi-quote is a later refinement.
    cash = free(quote)
    qty = {s: free(s.split("/")[0]) for s in symbols}
    return cash, qty
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_market.py -q`
Expected: PASS (new + existing — the existing `fetch_ohlcv_df`/`fetch_price`/`supports_short` tests are unaffected; `make_exchange("binance")` still builds a public client).

- [ ] **Step 5: Commit**

```bash
git add engine/market.py tests/test_market.py
git commit -m "feat: authenticated (read-only) exchange in shadow + fetch_balance"
```

---

### Task 3: Bot — shadow branch (`_run_shadow`)

**Files:**
- Modify: `engine/bot.py` (early `mode == "shadow"` branch; `+ _run_shadow`; `+ _status_payload` refactor; import `Position`)
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `cfg.mode`/`cfg.exchange_api_key`/`cfg.exchange_secret` (Task 1); `market.make_exchange(name, mode, api_key, secret)` + `market.fetch_balance` (Task 2); `broker.plan_order`, `state.append_decision`, `state.write_status`.
- Produces: shadow cycle logging intended orders + writing `status.json` with `mode`. The status payload now includes a top-level `mode` field (paper writes `"paper"`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bot.py`:

```python
def test_shadow_logs_intent_executes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.mode = "shadow"
    class ShadowMarket:
        def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
        def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
        def fetch_price(self, ex, sym): return 159.0
        def fetch_balance(self, ex, symbols): return 5000.0, {s: 0.0 for s in symbols}
    bot.run_once(cfg, market=ShadowMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    rec = _json.loads((tmp_path / "decisions.jsonl").read_text().strip().splitlines()[-1])
    assert rec["action"] == "buy" and rec["executed"] is False     # intended, not executed
    assert rec["reason"].startswith("[shadow]")
    assert not (tmp_path / "trades.csv").exists()                  # NO fill written
    assert not (tmp_path / "state.json").exists()                  # NO money state written
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["mode"] == "shadow"

def test_shadow_balance_failure_does_not_crash(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.mode = "shadow"
    class FailBalanceMarket:
        def make_exchange(self, name, mode="paper", api_key="", secret=""): return object()
        def fetch_ohlcv_df(self, ex, sym, tf, limit=200): return _df()
        def fetch_price(self, ex, sym): return 159.0
        def fetch_balance(self, ex, symbols): raise RuntimeError("auth failed")
    bot.run_once(cfg, market=FailBalanceMarket(), strategy=_strat(Decision(action="hold")))
    assert (tmp_path / "status.json").exists()                     # cycle survived, status still written

def test_paper_mode_still_simulates(tmp_path):
    cfg = _cfg(tmp_path)   # mode defaults "paper"
    bot.run_once(cfg, market=FakeMarket(), strategy=_strat(Decision(action="buy", size=1.0)))
    st = load_state(str(tmp_path), 10000.0, ["BTC/USDT"])
    assert st.positions["BTC/USDT"].qty > 0                        # paper path unchanged
    data = _json.loads((tmp_path / "status.json").read_text())
    assert data["mode"] == "paper"                                 # status now carries mode
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_bot.py -k "shadow or paper_mode_still" -q`
Expected: FAIL — shadow not implemented / `status.json` has no `mode`.

- [ ] **Step 3: Implement**

In `engine/bot.py`, extend the models import:

```python
from engine.models import Order, Position
```

Add a `_status_payload` helper (above `run_once`):

```python
def _status_payload(cfg, ts, funding_accrued, last_funding_ts):
    return {
        "ts": ts,
        "mode": cfg.mode,
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

In `engine/bot.py`, add the early branch at the top of `run_once` (right after the `strategy = ...` line, before `with state_mod.acquire_lock(...)`):

```python
    if cfg.mode == "shadow":
        _run_shadow(cfg, market, strategy)
        return
```

In `engine/bot.py`, REPLACE the paper status-write block (the final `try: state_mod.write_status({...}) except ...`) with the helper call:

```python
        try:                                     # advisory: a status write error never aborts the cycle
            state_mod.write_status(
                _status_payload(cfg, ts, st.funding_accrued, st.last_funding_ts), cfg.data_dir)
        except Exception as e:
            log.warning("status snapshot write failed: %s", e)
```

In `engine/bot.py`, add the `_run_shadow` function (after `run_once`):

```python
def _run_shadow(cfg, market, strategy) -> None:
    """Dry-run against the REAL account: read balance + price, log the order we WOULD place, execute nothing."""
    with state_mod.acquire_lock(cfg.data_dir):
        exchange = market.make_exchange(cfg.exchange, cfg.mode,
                                        cfg.exchange_api_key, cfg.exchange_secret)
        if cfg.risk.allow_short is None:
            cfg.risk.allow_short = market_mod.supports_short(exchange)
        ts = _now()
        bd = (sentiment_mod.breakdown(cfg.symbols, cfg) if cfg.sentiment.enabled else {})
        try:
            cash, qty_by = market.fetch_balance(exchange, cfg.symbols)
        except Exception as e:                   # bad/missing key or network -> no decisions, no crash
            log.warning("shadow: balance fetch failed: %s", e)
            print(f"[SHADOW] balance fetch failed ({e}); no decisions this cycle")
            cash, qty_by = 0.0, {}

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

            feats["price"] = price
            feats["sentiment"] = bd.get(sym, {}).get("blended", 0.0)
            feats["allow_short"] = bool(cfg.risk.allow_short)
            prices[sym] = price
            pos = Position(sym, qty=qty_by.get(sym, 0.0))         # real holding; no entry/stop tracking
            equity = cash + sum(qty_by.get(s, 0.0) * prices.get(s, 0.0) for s in cfg.symbols)
            decision = strategy(feats, pos, cash, cfg)
            order = broker.plan_order(decision, pos, cash, price, equity, cfg.risk)

            action = order.side if order else "hold"
            state_mod.append_decision(
                {"ts": ts, "symbol": sym, "action": action,
                 "reason": f"[shadow] {decision.reason}", "price": price, "executed": False},
                cfg.data_dir)
            if order is None:
                print(f"[SHADOW][{sym}] HOLD @ {price:.2f} — {decision.reason}")
            else:
                print(f"[SHADOW][{sym}] would {order.side.upper()} {order.qty:.6f} @ ~{price:.2f}")

        try:                                     # advisory; mode=shadow, no funding state in shadow
            state_mod.write_status(_status_payload(cfg, ts, 0.0, None), cfg.data_dir)
        except Exception as e:
            log.warning("status snapshot write failed: %s", e)
```

- [ ] **Step 4: Run the engine suite**

Run: `python -m pytest -q`
Expected: PASS — new shadow tests + every existing test (paper path byte-identical; the only behavioral delta is `status.json` now carrying `mode`, which existing status tests don't forbid).

- [ ] **Step 5: Commit**

```bash
git add engine/bot.py tests/test_bot.py
git commit -m "feat: shadow-mode bot branch — logs intended orders, executes nothing"
```

---

### Task 4: Dashboard — Mode chip

**Files:**
- Modify: `desktop/src/lib/parse.ts` (`Status` gains `mode?`)
- Modify: `desktop/src/renderer/src/components/StatusStrip.tsx` (Mode chip)

**Interfaces:**
- Consumes: `status.json`'s new `mode` field (Task 3).

- [ ] **Step 1: Add the type field**

In `desktop/src/lib/parse.ts`, extend the `Status` type with `mode`:

```typescript
export type Status = { ts: string; strategy: string; exchange: string; mode?: string;
                       risk: RiskStatus; funding: FundingStatus };
```

- [ ] **Step 2: Add the Mode chip**

In `desktop/src/renderer/src/components/StatusStrip.tsx`, add Mode as the FIRST chip in the `chips` array:

```tsx
  const chips: [string, string][] = [
    ["Mode", (status.mode ?? "paper").toUpperCase()],
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
Expected: vitest PASS (20 — the optional `mode?` doesn't break existing Status fixtures); build exit 0.

- [ ] **Step 4: Commit**

```bash
git add desktop/src/lib/parse.ts desktop/src/renderer/src/components/StatusStrip.tsx
git commit -m "feat: dashboard Mode chip (PAPER / SHADOW)"
```

---

### Task 5: README + final verification

**Files:**
- Modify: `README.md`
- Test: full suites + Playwright

- [ ] **Step 1: Update README**

Add a `## Shadow mode (real-account dry-run)` section to `README.md` (after the Funding section, before Tests), clean ASCII:

```markdown
## Shadow mode (real-account dry-run)

Set `mode: shadow` to run the bot against your **real exchange account read-only** — it fetches
your real balance + price, computes the order it *would* place, and logs it (decisions show
`executed: false` with a `[shadow]` reason), but **places nothing and moves no money**. Use a
**read-only / no-trade API key** in `.env` (`EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET`). The
dashboard's Status strip shows `MODE: SHADOW`. This is the dry-run stage before live execution:
`paper` (simulated) → `shadow` (real reads, zero execution) → live (slice 2). `create_order` does
not exist in the codebase yet — shadow cannot trade.
```

- [ ] **Step 2: Full engine + desktop suites**

Run: `python -m pytest -q && cd desktop && npm test && npm run build`
Expected: engine all-green; desktop vitest 20; build exit 0.

- [ ] **Step 3: Audit — shadow truly cannot trade**

Run: `grep -rn "create_order\|cancel_order" engine/`
Expected: **no matches** — proves no order-placement call exists anywhere in the engine after this slice.

- [ ] **Step 4: Playwright visual verification**

Build the renderer, serve a harness with a `status` whose `mode` is `"shadow"`, and screenshot the Status strip at 1280 / 768 / 375. Confirm the `MODE: SHADOW` chip renders first; confirm a `mode: "paper"` snapshot shows `MODE: PAPER`. Clean up harness artifacts after.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document shadow mode (real-account dry-run, read-only key)"
```

---

## Self-Review

**Spec coverage:**
- `mode` + credential resolution (env-named) → Task 1 ✓
- authenticated read-only exchange + `fetch_balance` → Task 2 ✓
- shadow bot branch (real balance → intent log, no fill/persist/force_close) + `status.json mode` → Task 3 ✓
- dashboard Mode chip → Task 4 ✓
- README + `.env.example` + the no-`create_order` audit → Tasks 1 & 5 ✓
- paper byte-identical (default), shadow read-only, gate unchanged → Tasks 1–3 (paper `make_exchange(cfg.exchange)` unchanged; shadow asserts no trades/state written) ✓

**Type/signature consistency:** `make_exchange(name, mode="paper", api_key="", secret="")` — Task 2 defines, Task 3 calls with `cfg.mode`/`cfg.exchange_api_key`/`cfg.exchange_secret` (Task 1) ✓. `fetch_balance(exchange, symbols) -> (cash, {symbol: qty})` — Task 2 defines, Task 3 consumes ✓. `_status_payload(cfg, ts, funding_accrued, last_funding_ts)` adds `mode` — Task 3 defines + both paper and shadow call it ✓. `Status.mode?` — Task 4 defines, the chip consumes ✓.

**Placeholder scan:** none — every code step shows full code and exact insertion points; the Task 3 paper status-write replacement and the early branch are given verbatim. The `.env.example` step instructs reading the file first before appending.
